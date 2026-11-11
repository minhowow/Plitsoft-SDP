"""저장소 검토(`policypack review`): 프로필 → 이해 → 의무별 근거 찾기 → 반박 검증 → 체크리스트.

1. 프로필(profile): 규칙 신호로 기능을 알아본다. 모델 호출 0회.
2. 이해: 조사 모델이 저장소를 읽고 무슨 서비스인지 적고, 신호가 놓친 기능을 더하거나 아닌 기능을 빼고, 개인정보
   흐름(마디와 화살표)을 그린다. 더하기·빼기·마디·화살표 모두 인용이 관문을 통과해야 받는다.
3. 의무: 기능에 붙은 의무 전부가 목록 층이다. 그 가운데 검토 층 후보(조문 인용 대조 통과·확신 높음·지위가 아님)와 내장
   팩(kr-core)이 다루는 의무를 묻는다. 묶음은 기능 하나(의무 최대 8개) 또는 의무 하나다(`batch`).
4. 근거 찾기: 조사 모델이 의무마다 `충족 근거 있음 / 확인할 것 / 해당 없음 / 모름` 과 인용·질문을 낸다.
   목록에서 빼는 답(충족·해당 없음)은 인용이 관문을 통과하고 시험·설정 파일이 아니어야 받고, 아니면 '확인할 것'이다.
5. 반박: 다른 모델이 빼는 답에는 "지키지 않은 곳을 찾아라", '확인할 것'에는 "지킨 근거를 찾아라"로 다시 본다.
   뒤집는 답도 인용이 관문을 통과해야 받는다. '모름'은 반박하지 않는다.

지키는 것: 인용 관문, 비밀값 가리기·비밀 파일 거부(judge/agent.RepoTools), 저장소 밖 읽기 금지, 저장소당 상한(어림
금액·시간). 상한 때문에 묻지 못한 의무는 '모름'으로 싣고 까닭을 적는다. 동시 요청은 429 를 보면 반으로 줄인다.
기존 정책 팩(kr-core)의 정적 결과는 같은 의무 id 의 체크리스트 항목에 `static` 으로 붙고, 그 의무의 질문에 힌트로
들어간다.
"""

from __future__ import annotations

import io
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

from policypack import __version__
from policypack.evaluate.agent_pass import gate
from policypack.index.roles import SERVICE, classify
from policypack.judge.agent import AgentAnswer, AgentJudge
from policypack.profile import load_duties, load_features, profile
from policypack.review import prompts as P

REVIEW_VERSION = 1
PRIORITY = ("common", "signup", "auth", "genai", "external-transfer")
"""상한에 걸리면 이 순서로 먼저 묻는다(거의 모든 서비스, 가입, 로그인, AI, 외부 전송). 나머지는 프로필의 기능 순서다."""
GROUP_MAX = 8
DROPS = ("evidence-found", "not-applicable")
NOT_ANSWERED = {"cost-cap": "저장소당 금액 상한에 걸려 묻지 못했습니다", "time-cap": "시간 상한에 걸렸습니다"}
PRICES = {"opus": (15.0, 75.0), "sonnet": (3.0, 15.0), "haiku": (1.0, 5.0)}
"""100만 토큰당 달러(입력, 출력). 보수 단가다. 모르는 모델은 opus 값으로 센다. 캐시 쓰기는 입력의 1.25배, 읽기는
0.1배."""
RESERVE = {"haiku": 0.15, "sonnet": 0.45, "opus": 2.0}
MAX_TOKENS = 16000
"""답 하나의 출력 상한. 이해 단계의 흐름과 기능 묶음의 답이 8192 에서 잘렸다(11/11 실측). 쓴 만큼만 청구된다."""
"""질문 하나를 새로 보내기 전에 남아 있어야 하는 어림 금액. 대화 중에는 멈출 수 없어 상한을 넘지 않게 미리 남긴다."""


# ── 상한과 속도 ─────────────────────────────────────────────────────


def _tier(model: str) -> str:
    return next((t for t in PRICES if t in model), "opus")


def usd(model: str, usage: dict) -> float:
    pin, pout = PRICES[_tier(model)]
    return (
        usage.get("input_tokens", 0) * pin
        + usage.get("cache_creation_input_tokens", 0) * pin * 1.25
        + usage.get("cache_read_input_tokens", 0) * pin * 0.1
        + usage.get("output_tokens", 0) * pout
    ) / 1e6


class Spend:
    """어림 금액. 질문을 보내기 전에 `allows` 로 묻고, 답을 받으면 `add` 로 더한다."""

    def __init__(self, cap: float) -> None:
        self.cap, self.usd, self.usage = cap, 0.0, {}
        self._lock = threading.Lock()

    def allows(self, model: str) -> bool:
        with self._lock:
            return self.usd + RESERVE[_tier(model)] <= self.cap

    def add(self, model: str, usage: dict) -> None:
        with self._lock:
            self.usd += usd(model, usage)
            mine = self.usage.setdefault(model, {})
            for k, v in usage.items():
                if isinstance(v, int):
                    mine[k] = mine.get(k, 0) + v


class Throttle:
    """동시에 보내는 요청 수. 429 를 받으면 반으로 줄인다(1 까지). 판정기의 전송을 감싸 쓴다."""

    def __init__(self, limit: int) -> None:
        self.start = self.limit = max(1, limit)
        self.active = self.rate_limited = 0
        self._cv = threading.Condition()

    def __enter__(self):
        with self._cv:
            while self.active >= self.limit:
                self._cv.wait()
            self.active += 1

    def __exit__(self, *exc):
        with self._cv:
            self.active -= 1
            self._cv.notify_all()

    def saw(self, status: int) -> None:
        if status == 429:
            with self._cv:
                self.rate_limited += 1
                self.limit = max(1, self.limit // 2)

    def wrap(self, send):
        def throttled(body: dict) -> dict:
            with self:
                return send(body)

        return throttled


@dataclass
class Limits:
    usd: float = 5.0
    seconds: float = 360.0
    concurrency: int = 4
    batch: str = "feature"  # feature | duty


# ── 인용 ─────────────────────────────────────────────────────────────


def check(root: Path, citations: list[dict]) -> list[dict]:
    """인용 관문(agent_pass.gate)에 더해, 시험·픽스처·설정 파일의 줄은 받지 않는다(why: test-file)."""
    out = gate(root, citations)
    for c in out:
        if c["ok"]:
            rel = c["file"].removeprefix("./").lstrip("/")
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
            if classify(rel, text) not in SERVICE:
                c["ok"], c["why"] = False, "test-file"
            else:
                c["file"] = rel
    return out


def grounded(cs: list[dict]) -> bool:
    return any(c["ok"] for c in cs)


# ── 질문 기록 ─────────────────────────────────────────────────────────


@dataclass
class Run:
    root: Path
    investigator: AgentJudge
    checker: AgentJudge
    limits: Limits
    spend: Spend
    questions: list[dict] = field(default_factory=list)
    t0: float = field(default_factory=time.monotonic)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def ask(
        self, stage: str, judge: AgentJudge, prompt: str, budget: int, meta: dict, key: str
    ) -> tuple[dict | None, str | None, int]:
        """상한 안이면 묻고, 답에서 `key` 를 가진 JSON 객체를 읽고, 기록한다. (객체, 실패 까닭, 기록 번호).
        상한에 걸리면 묻지 않고 cost-cap·time-cap 이다. 답이 JSON 이 아니면 도구 없이 한 번 더, 그 답을 요청한 JSON 으로
        옮겨 달라고 묻는다(repaired). 그래도 안 되면 parse 이고 답의 글 앞부분을 기록에 남긴다."""
        if not self.spend.allows(judge.model):
            return None, "cost-cap", self._log(stage, judge, meta, None, "cost-cap")
        if judge.deadline is not None and time.monotonic() >= judge.deadline:
            return None, "time-cap", self._log(stage, judge, meta, None, "time-cap")
        start = time.monotonic()
        text, ans = judge.converse(prompt, self.root, budget, max_tokens=MAX_TOKENS)
        self.spend.add(judge.model, ans.usage)
        failure, doc, extra = ans.failure, None, {}
        if failure and failure.startswith("time"):
            failure = "time-cap"
        if not failure:
            doc = P.parse_object(text, key)
            if doc is None and text.strip() and self.spend.allows(judge.model):
                fixed, fix = judge.converse(P.REPAIR.format(key=key, raw=text[-24000:]), self.root, 0, MAX_TOKENS)
                self.spend.add(judge.model, fix.usage)
                ans.calls += fix.calls
                for k, v in fix.usage.items():
                    ans.usage[k] = ans.usage.get(k, 0) + v
                doc = P.parse_object(fixed, key) if not fix.failure else None
                extra["repaired"] = doc is not None
            if doc is None:
                failure, extra["raw"] = "parse", text[:2000]
        timing = {"started": round(start - self.t0, 1), "seconds": round(time.monotonic() - start, 1)}
        return doc, failure, self._log(stage, judge, {**meta, **timing, **extra}, ans, failure)

    def _log(self, stage, judge, meta, ans: AgentAnswer | None, failure: str | None) -> int:
        rec = {"stage": stage, "model": judge.model, **meta, "failure": failure}
        if ans is not None:
            rec |= {
                "calls": ans.calls,
                "tool_calls": ans.tool_calls,
                "budget": ans.budget,
                "usage": ans.usage,
                "usd": round(usd(judge.model, ans.usage), 4),
                "sent": {
                    "read": ans.read_files,
                    "searches": ans.searches,
                    "matched": ans.matched_files,
                    "listed": ans.listed,
                    "refused": ans.refused,
                    "masked": ans.masked,
                },
            }
        with self._lock:
            rec["n"] = len(self.questions)
            self.questions.append(rec)
            return rec["n"]


# ── 1·2. 프로필과 이해 ───────────────────────────────────────────────


def _where(e: dict) -> str:
    return f"`{e['file']}`" + (f":{e['line']}" if e.get("line") else "") + f" ({e['what']})"


def _found_lines(prof: dict) -> str:
    rows = [f"- {f['id']} ({f['name']}): " + "; ".join(_where(e) for e in f["evidence"][:3]) for f in prof["features"]]
    return "\n".join(rows) or "- (없음)"


def understand(run: Run, prof: dict, catalog: dict[str, str]) -> dict:
    budget = 40
    prompt = P.UNDERSTAND.format(
        found=_found_lines(prof),
        catalog="\n".join(f"- {k}: {v}" for k, v in catalog.items()),
        budget=budget,
        cite=P.CITE,
        rules=P.RULES,
    )
    doc, _, _ = run.ask("understand", run.investigator, prompt, budget, {}, "summary")
    out = {"summary": "", "added": [], "removed": [], "nodes": [], "edges": [], "rejected_claims": 0, "answered": False}
    if doc is None:
        return out
    out["answered"] = True
    out["summary"] = str(doc.get("summary") or "")[:800]
    for key, dest in (("features_added", "added"), ("features_removed", "removed")):
        for item in doc.get(key) or []:
            if not isinstance(item, dict) or item.get("feature") not in catalog:
                continue
            cs = check(run.root, P.citations_of(item))
            rec = {"feature": item["feature"], "reason": str(item.get("reason") or ""), "citations": cs}
            if grounded(cs):
                out[dest].append(rec)
            else:
                out["rejected_claims"] += 1
    flow = doc.get("flow") if isinstance(doc.get("flow"), dict) else {}
    kept: set[str] = set()
    for n in flow.get("nodes") or []:
        if not isinstance(n, dict) or not isinstance(n.get("id"), str):
            continue
        cs = check(run.root, P.citations_of(n))
        if not grounded(cs):
            out["rejected_claims"] += 1
            continue
        kind = n.get("kind") if n.get("kind") in ("input", "server", "store", "external") else "server"
        kept.add(n["id"])
        out["nodes"].append(
            {
                "id": n["id"],
                "kind": kind,
                "label": str(n.get("label") or "")[:80],
                "data": [str(x)[:40] for x in n.get("data") or []][:12],
                "citations": cs,
            }
        )
    for e in flow.get("edges") or []:
        if not isinstance(e, dict) or e.get("from") not in kept or e.get("to") not in kept:
            continue
        cs = check(run.root, P.citations_of(e))
        if not grounded(cs):
            out["rejected_claims"] += 1
            continue
        out["edges"].append(
            {"from": e["from"], "to": e["to"], "data": [str(x)[:40] for x in e.get("data") or []][:12], "citations": cs}
        )
    return out


# ── 3. 정적 결과(kr-core) ────────────────────────────────────────────


def static_results(root: Path) -> tuple[dict[str, list[dict]], str | None]:
    """내장 팩으로 정적 검사(모델 호출 0회)를 돌려 의무 id 별 경고를 모은다. 실패하면 ({}, 까닭)."""
    import json

    from policypack.cli import _main, _report_root
    from policypack.defaults import default_pack
    from policypack.pack.loader import load_pack

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = _main(["scan", str(root), "--output-format", "json", "--exit-zero"])
    if code != 0:
        return {}, (err.getvalue().strip().splitlines() or [f"종료 코드 {code}"])[-1][:300]
    report = json.loads(out.getvalue())
    duties_of = {p.id: list(p.duties) for p in load_pack(default_pack()).policies}
    base = _report_root([root])
    by_duty: dict[str, list[dict]] = {}
    for f in report["findings"]:
        p = (base / f["file"]).resolve()
        rel = p.relative_to(root).as_posix() if p.is_relative_to(root) else f["file"]
        item = {"policy": f["policy"], "rule": f["rule"], "outcome": f["outcome"], "file": rel, "line": f["line"]}
        for d in duties_of.get(f["policy"], []):
            by_duty.setdefault(d, []).append(item)
    return by_duty, None


# ── 4·5. 근거 찾기와 반박 ─────────────────────────────────────────────


def _evidence_lines(feature: dict | None) -> str:
    if not feature:
        return "- (거의 모든 서비스에 걸리는 의무다. 서비스 전체에서 찾는다)"
    rows = [f"- {_where(e)}" for e in feature["evidence"]]
    model = feature.get("model_citations", [])[:3]
    rows += [f"- `{c['file']}`:{c['line']} {c['text'][:120]} (이해 단계)" for c in model]
    return f"{feature['name']}\n" + "\n".join(rows)


def _static_lines(group: list[dict], static: dict[str, list[dict]]) -> str:
    rows = [
        f"- [{d['id']}] {s['policy']}/{s['rule']} {s['outcome']} `{s['file']}`:{s['line']}"
        for d in group
        for s in static.get(d["id"], [])[:5]
    ]
    return "\n## 정적 검사가 찾은 곳(이 의무와 같은 정책)\n" + "\n".join(rows) + "\n" if rows else ""


def _budget(n: int, base: int, per: int, cap: int) -> int:
    return min(base + per * max(0, n - 1), cap)


def investigate(run: Run, group: list[dict], feature: dict | None, summary: str, static: dict) -> dict[str, dict]:
    budget = _budget(len(group), 20, 3, 40)
    prompt = P.INVESTIGATE.format(
        summary=summary or "(이해 단계의 요약 없음)",
        evidence=_evidence_lines(feature),
        static=_static_lines(group, static),
        duties="\n".join(P.duty_block(d) for d in group),
        budget=budget,
        cite=P.CITE,
        rules=P.RULES,
    )
    meta = {"feature": group[0]["feature"], "duties": [d["id"] for d in group]}
    doc, failure, qn = run.ask("investigate", run.investigator, prompt, budget, meta, "results")
    results: dict[str, dict] = {}
    if failure in ("cost-cap", "time-cap") and doc is None and not run.questions[qn].get("calls"):
        return {d["id"]: {"asked": False, "why": failure, "q": qn} for d in group}
    wanted = {d["id"] for d in group}
    for r in (doc or {}).get("results") or []:
        if not isinstance(r, dict) or r.get("duty") not in wanted or r.get("status") not in P.STATUS_OF:
            continue
        status = P.STATUS_OF[r["status"]]
        cs = check(run.root, P.citations_of(r))
        first = status
        if status in DROPS and not grounded(cs):
            status = "to-check"
        results[r["duty"]] = {
            "asked": True,
            "status": status,
            "answered": first,
            "citations": cs,
            "question": str(r.get("question") or "")[:400],
            "reason": str(r.get("reason") or "")[:800],
            "q": qn,
        }
    for d in group:
        if d["id"] not in results:
            results[d["id"]] = {"asked": True, "why": failure or "no-answer", "q": qn}
    return results


def rebut(run: Run, group: list[dict], first: dict[str, dict], summary: str) -> dict[str, dict]:
    items = [d for d in group if first.get(d["id"], {}).get("status") in (*DROPS, "to-check")]
    if not items:
        return {}
    budget = _budget(len(items), 15, 3, 35)
    blocks = []
    for d in items:
        f = first[d["id"]]
        ok = [c for c in f["citations"] if c["ok"]]
        blocks.append(
            P.duty_block(d)
            + f"\n  앞 판단: {P.STATUS_KO[f['status']]} — {f['reason']}"
            + (f"\n  앞 인용: {P.cite_lines(ok)}" if ok else "")
        )
    prompt = P.REBUT.format(
        summary=summary or "(요약 없음)", items="\n".join(blocks), budget=budget, cite=P.CITE, rules=P.RULES
    )
    meta = {"feature": group[0]["feature"], "duties": [d["id"] for d in items]}
    doc, failure, qn = run.ask("rebut", run.checker, prompt, budget, meta, "results")
    if failure in ("cost-cap", "time-cap") and doc is None and not run.questions[qn].get("calls"):
        return {d["id"]: {"result": "not-run", "why": failure, "q": qn} for d in items}
    out: dict[str, dict] = {}
    wanted = {d["id"] for d in items}
    for r in (doc or {}).get("results") or []:
        if not isinstance(r, dict) or r.get("duty") not in wanted or r.get("result") not in ("유지", "뒤집음"):
            continue
        cs = check(run.root, P.citations_of(r))
        rec = {"citations": cs, "reason": str(r.get("reason") or "")[:800], "q": qn}
        if r["result"] == "유지":
            out[r["duty"]] = {"result": "upheld", **rec}
            continue
        before = first[r["duty"]]["status"]
        claimed = P.STATUS_OF.get(r.get("status") or "", "")
        # 빼는 답을 깨면 '확인할 것', '확인할 것'을 깨면 그 모델이 말한 빼는 상태(없으면 충족 근거 있음)
        after = "to-check" if before in DROPS else claimed if claimed in DROPS else "evidence-found"
        if grounded(cs):
            out[r["duty"]] = {"result": "overturned", "status": after, **rec}
        else:
            out[r["duty"]] = {"result": "overturn-ungrounded", "status": after, **rec}
    for d in items:
        out.setdefault(d["id"], {"result": "not-run", "why": failure or "no-answer", "q": qn})
    return out


def _item(d: dict, first: dict, check_: dict | None, static: list[dict]) -> dict:
    base = {
        "duty": d["id"],
        "feature": d["feature"],
        "law": d["law"],
        "article": d["article"],
        "title": d["title"],
        "duty_text": d["duty"],
        "url": d["url"],
        "quote": d["quote"],
        "krcore": d.get("krcore", False),
        "static": static,
    }
    if not first.get("asked") or "status" not in first:
        why = first.get("why") or "no-answer"
        return {
            **base,
            "status": "unknown",
            "asked": bool(first.get("asked")),
            "not_answered": why,
            "first": None,
            "verification": {"result": "not-run", "why": why},
            "citations": [],
            "question": "",
            "reason": NOT_ANSWERED.get(why, "답을 받지 못했습니다"),
        }
    status, citations = first["status"], first["citations"]
    verification = {"result": "not-run", "why": "unknown" if status == "unknown" else "no-answer"}
    if check_:
        verification = {k: v for k, v in check_.items() if k != "q"}
        if check_["result"] == "overturned":
            status, citations = check_["status"], check_["citations"]
    return {
        **base,
        "status": status,
        "asked": True,
        "first": {k: first[k] for k in ("answered", "status", "citations", "reason", "question")},
        "verification": verification,
        "citations": citations,
        "question": first["question"],
        "reason": first["reason"] if status == first["status"] else verification.get("reason", ""),
    }


# ── 전체 ─────────────────────────────────────────────────────────────


def _blank(fid: str, name: str) -> dict:
    return {"id": fid, "name": name, "sources": [], "evidence": [], "evidence_total": 0, "model_citations": []}


def select(prof: dict, und: dict, static: dict[str, list[dict]]) -> tuple[list[dict], list[dict], list[dict]]:
    """(기능 목록, 목록 층 의무, 검토 층 의무). 기능은 신호 + 이해 단계가 더한 것 − 뺀 것 + 정적 검사가 찾은 것."""
    spec = load_features()
    names = {f["id"]: f["name"] for f in spec["features"]}
    duties = load_duties()
    by_id = {d["id"]: d for d in duties}
    removed = {r["feature"]: r for r in und["removed"]}
    features: dict[str, dict] = {}
    for f in prof["features"]:
        features[f["id"]] = {
            "id": f["id"],
            "name": f["name"],
            "sources": ["signal"],
            "evidence": f["evidence"],
            "evidence_total": f["evidence_total"],
            "model_citations": [],
        }
    for a in und["added"]:
        f = features.setdefault(a["feature"], _blank(a["feature"], names[a["feature"]]))
        if "model" not in f["sources"]:
            f["sources"].append("model")
        f["model_citations"] += [c for c in a["citations"] if c["ok"]]
        f["model_reason"] = a["reason"]
    for did, hits in static.items():
        fid = by_id[did]["feature"] if did in by_id else None
        if fid and fid in names and hits:
            f = features.setdefault(fid, _blank(fid, names[fid]))
            if "static" not in f["sources"]:
                f["sources"].append("static")
    for fid in list(features):
        if fid in removed and features[fid]["sources"] == ["signal"]:
            features[fid]["removed"] = {"reason": removed[fid]["reason"], "citations": removed[fid]["citations"]}
    live = [f for f in features.values() if "removed" not in f]
    service = [f for f in live if f["id"] not in ("web-ui", "mobile-app")]
    ids = {f["id"] for f in live} | ({"common"} if service else set())
    listed = [d for d in duties if d["feature"] in ids]
    order = {fid: i for i, fid in enumerate(PRIORITY)}
    rest = {f["id"]: len(PRIORITY) + i for i, f in enumerate(spec["features"])}
    review = [
        d for d in listed if d["review_candidate"] or (d.get("krcore") and (static.get(d["id"]) or d["feature"] in ids))
    ]
    review.sort(key=lambda d: (order.get(d["feature"], rest.get(d["feature"], 99)), d["id"]))
    return list(features.values()), listed, review


def groups_of(review: list[dict], batch: str) -> list[list[dict]]:
    if batch == "duty":
        return [[d] for d in review]
    out: list[list[dict]] = []
    for d in review:
        if out and out[-1][0]["feature"] == d["feature"] and len(out[-1]) < GROUP_MAX:
            out[-1].append(d)
        else:
            out.append([d])
    return out


def plan(root: Path, use_static: bool = True) -> dict:
    """모델을 부르지 않고 무엇을 물을지만 센다(비용 어림용)."""
    root = root.resolve()
    prof = profile(root)
    static, err = static_results(root) if use_static else ({}, None)
    empty = {"summary": "", "added": [], "removed": []}
    features, listed, review = select(prof, empty, static)
    return {
        "features": [f["id"] for f in features],
        "listed": len(listed),
        "review": len(review),
        "questions": {b: len(groups_of(review, b)) for b in ("feature", "duty")},
        "static_error": err,
    }


def review(
    root: Path,
    investigator: AgentJudge,
    checker: AgentJudge,
    limits: Limits | None = None,
    use_static: bool = True,
    throttles: tuple[Throttle, ...] = (),
) -> dict:
    limits = limits or Limits()
    root = root.resolve()
    t0 = time.monotonic()
    for j in (investigator, checker):
        j.deadline = t0 + limits.seconds
    run = Run(root, investigator, checker, limits, Spend(limits.usd), t0=t0)

    prof = profile(root)
    static, static_err = static_results(root) if use_static else ({}, None)
    catalog = {f["id"]: f["name"] for f in load_features()["features"]}
    und = understand(run, prof, catalog)
    features, listed, review_duties = select(prof, und, static)
    by_feature = {f["id"]: f for f in features}
    groups = groups_of(review_duties, limits.batch)

    def work(group: list[dict]) -> tuple[dict, dict]:
        first = investigate(run, group, by_feature.get(group[0]["feature"]), und["summary"], static)
        return first, rebut(run, group, first, und["summary"])

    firsts: dict[str, dict] = {}
    checks: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max(1, limits.concurrency)) as pool:
        for first, chk in pool.map(work, groups):
            firsts |= first
            checks |= chk

    checklist = [_item(d, firsts.get(d["id"], {}), checks.get(d["id"]), static.get(d["id"], [])) for d in review_duties]
    seconds = time.monotonic() - t0
    return _report(run, prof, und, features, listed, checklist, static, static_err, seconds, throttles)


def _report(run: Run, prof, und, features, listed, checklist, static, static_err, seconds, throttles) -> dict:
    in_checklist = {c["duty"] for c in checklist}
    cites = [c for q in checklist for c in (q["first"] or {}).get("citations", [])]
    cites += [c for q in checklist for c in q["verification"].get("citations", [])]
    for part in ("nodes", "edges"):
        cites += [c for x in und[part] for c in x["citations"]]
    masked: dict[str, int] = {}
    refused: set[str] = set()
    for q in run.questions:
        for k, v in (q.get("sent") or {}).get("masked", {}).items():
            masked[k] = masked.get(k, 0) + v
        refused |= set((q.get("sent") or {}).get("refused", []))
    counts: dict[str, int] = {}
    for c in checklist:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    verdicts: dict[str, int] = {}
    for c in checklist:
        verdicts[c["verification"]["result"]] = verdicts.get(c["verification"]["result"], 0) + 1
    not_asked: dict[str, int] = {}
    for c in checklist:
        if c["status"] == "unknown" and c.get("not_answered"):
            not_asked[c["not_answered"]] = not_asked.get(c["not_answered"], 0) + 1
    return {
        "review_version": REVIEW_VERSION,
        "tool": {"name": "policypack", "version": __version__},
        "profile": {
            "summary": und["summary"],
            "features": features,
            "test_only": prof["test_only"],
            "files": prof["files"],
        },
        "data_flow": {"nodes": und["nodes"], "edges": und["edges"]},
        "obligations": {
            "listed": [
                {
                    "id": d["id"],
                    "feature": d["feature"],
                    "law": d["law"],
                    "article": d["article"],
                    "title": d["title"],
                    "duty": d["duty"],
                    "url": d["url"],
                    "in_checklist": d["id"] in in_checklist,
                }
                for d in listed
            ],
            "status_only": sum(1 for d in load_duties() if d["feature"] == "status"),
        },
        "checklist": checklist,
        "run": {
            "models": {"investigate": run.investigator.model, "verify": run.checker.model},
            "batch": run.limits.batch,
            "limits": {"usd": run.limits.usd, "seconds": run.limits.seconds, "concurrency": run.limits.concurrency},
            "seconds": round(seconds, 1),
            "calls": sum(q.get("calls", 0) for q in run.questions),
            "usage": run.spend.usage,
            "usd_estimate": round(run.spend.usd, 4),
            # 동시 요청 수. 429 를 받을 때마다 반으로 줄였다(판정기마다 하나)
            "concurrency": [{"start": t.start, "end": t.limit, "rate_limited": t.rate_limited} for t in throttles],
            "status_counts": counts,
            "verification_counts": verdicts,
            "citations": len(cites),
            "citations_rejected": sum(1 for c in cites if not c["ok"]),
            "understanding": {"answered": und["answered"], "rejected_claims": und["rejected_claims"]},
            "not_asked": not_asked,
            "masked": masked,
            "refused": sorted(refused),
            "static": {"ran": not static_err, "error": static_err, "duties": len(static)},
            "questions": run.questions,
        },
    }


def build_judge(spec: str, throttle: Throttle, env: dict | None = None) -> AgentJudge:
    """`anthropic:<모델>` → 동시 요청 수를 `throttle` 로 묶은 에이전트 판정기. 키는 ANTHROPIC_API_KEY 에서 읽는다."""
    import os

    from policypack.judge.anthropic_api import MODELS
    from policypack.judge.http import http_transport

    kind, _, model = spec.partition(":")
    if kind != "anthropic" or not model:
        raise ValueError(f"판정기를 알 수 없습니다: {spec!r} (예: anthropic:claude-haiku-5-5)")
    key = (env if env is not None else os.environ).get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY 가 없습니다")
    return AgentJudge(MODELS.get(model, model), throttle.wrap(http_transport(key, on_retry=throttle.saw)))
