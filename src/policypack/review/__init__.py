"""저장소 검토(`policypack review`): 프로필 → 이해 → 의무별 근거 찾기 → 반박 검증 → 체크리스트.

1. 프로필(profile): 규칙 신호로 기능과 플랫폼(웹·모바일 앱·서버)을 알아본다. 모델 호출 0회.
2. 이해: 조사 모델이 저장소를 읽고 무슨 서비스인지 적고, 신호가 놓친 기능을 더하거나 아닌 기능을 빼고, 개인정보
   흐름(마디와 화살표)을 그린다. 더하기·빼기·마디·화살표 모두 인용이 관문을 통과해야 받는다. 같은 커밋의 앞 결과를
   넘기면(`reuse`) 묻지 않고 그 결과를 관문에 다시 걸어 쓴다.
3. 의무: 기능에 붙은 의무 전부가 목록 층이다. 그 가운데 검토 층 후보(조문 인용 대조 통과·확신 높음·지위가 아님)와 내장
   팩(kr-core)이 다루는 의무를 묻는다. 묶음은 의무 하나(기본) 또는 기능 하나(의무 최대 8개)다(`batch`).
4. 근거 찾기: 조사 모델이 의무마다 상태와 인용·검색·질문을 낸다. 상태(prompts.STATUS_LABEL)와 받는 조건:
     충족 근거 있음        인용이 관문을 통과해야 한다. 아니면 '저장소 밖에서 확인할 것'
     코드에서 본 것        걸리는 처리의 인용이 관문을 통과해야 한다. 아니면 '저장소 밖에서 확인할 것'
     저장소 밖에서 확인할 것 · 해당 여부부터 확인할 것   그대로
     해당 없음             걸리는 조건 자체가 없다는 답(applies '아니오'와 condition)이어야 하고, 찾아본 검색(정규식·
                           줄 수)을 도구가 저장소에서 다시 돌려 줄 수가 같아야 한다(부재의 증명). 증명이 없으면 '걸리지
                           않는 것으로 보임(확인 안 됨)'이고 확인 목록에 올리지 않는다. 조건은 있는데 지킨 처리만
                           없다는 답과, 그 기능이 있으면 걸리는 의무(features.yaml 의 whenever)에 기능이 있는 경우는
                           '코드에서 본 것', 조건을 말하지 않았으면 '해당 여부부터 확인할 것'이다(gate)
     충족(덧붙임)          인용이 조문이 요구하는 행위 자체여야 한다(shows '행위'). 이름·기본값뿐이면 '코드에서 본 것'
   시험·설정 파일의 줄은 인용으로 받지 않는다. 요건은 조문 인용에 있는 것만 묻는다.
   특정 품목(주류·도서 등, features.yaml 의 goods) 의무는 프로필에 그 품목 신호가 없으면 묻지 않고 '해당 여부부터
   확인할 것'에 한 묶음(group: goods)으로 싣는다.
5. 반박: 다른 모델이 빼는 답(충족·해당 없음·걸리지 않는 것으로 보임)에는 "지키지 않은 곳을 찾아라", 코드에서 본 것과
   저장소 밖에서 확인할 것에는 "지킨 근거를 찾아라"로 다시 본다. 뒤집는 답도 같은 조건(인용·검색)을 넘어야 받는다. 앞
   판단이 조문에 없는 요건을 들었는지도 적는다(off_quote). 해당 여부는 사업자의 판단이라 반박하지 않는다.
6. 체크리스트는 상태의 갈래 순(코드에서 본 것이 맨 위), 그 안에서는 거의 모든 서비스·가입·AI·외부 전송 순이다.
   기능 안에서는 핵심 의무(일반 범위 → 흔한 것 → 확신 높은 것)가 먼저이고 품목 의무가 맨 뒤다. 묻는 순서도 같아서
   상한에 걸려도 핵심은 묻는다. `summary` 에 갈래별 수와 맨 위 다섯 건, 묶음(groups)이 있다.

지키는 것: 인용 관문, 비밀값 가리기·비밀 파일 거부(judge/agent.RepoTools), 저장소 밖 읽기 금지, 저장소당 상한(어림
금액·시간). 상한 때문에 묻지 못한 의무는 '모름'으로 싣고 까닭을 적는다. 동시 요청은 429 를 보면 반으로 줄인다.
기존 정책 팩(kr-core)의 정적 결과는 같은 의무 id 의 체크리스트 항목에 `static` 으로 붙고, 그 의무의 질문에 힌트로
들어간다.
"""

from __future__ import annotations

import io
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout, suppress
from dataclasses import dataclass, field
from pathlib import Path

from policypack import __version__
from policypack.evaluate.agent_pass import gate
from policypack.index.roles import SERVICE, classify
from policypack.judge.agent import AgentAnswer, AgentJudge, RepoTools
from policypack.profile import load_duties, load_features, profile
from policypack.review import prompts as P

REVIEW_VERSION = 2
"""1 → 2: '확인할 것'을 세 갈래(seen-in-code·check-outside·check-applicability)로 나누고, 부재 증명(searches)과
'걸리지 않는 것으로 보임'(likely-not-applicable)을 더했다. 체크리스트를 갈래 순으로 늘어놓고 summary 를 더했다.
2판 안의 덧붙임(11/12): 답의 applies·condition·missing·shows 와 관문이 바꾼 까닭(gate), 품목 묶음(group,
summary.groups), not_answered 'goods-not-detected', 인용 why 'profile'(기능이 있다는 프로필 신호를 조건의 근거로
붙인 것)."""
PRIORITY = ("common", "signup", "genai", "external-transfer")
"""상한에 걸리면 이 순서로 먼저 묻고, 체크리스트의 같은 갈래 안에서도 이 순서로 놓는다. 나머지는 기능 목록의 순서다."""
GROUP_MAX = 8
DROPS = ("evidence-found", "not-applicable", "likely-not-applicable")
"""목록에서 빼는 상태. 반박이 "지키지 않은 곳"을 찾는다."""
TO_CHECK = ("seen-in-code", "check-outside")
"""반박이 "지킨 근거"를 찾는 상태. 해당 여부(check-applicability)는 사업자의 판단이라 묻지 않는다."""
PLATFORM_KO = {"web": "웹", "mobile": "모바일 앱", "server": "서버"}
NOT_ANSWERED = {"cost-cap": "저장소당 금액 상한에 걸려 묻지 못했습니다", "time-cap": "시간 상한에 걸렸습니다"}
GOODS_LABEL = "특정 품목을 판다면 확인할 것"
FIRST_KEYS = (
    *("answered", "status", "citations", "searches"),
    *("applies", "condition", "missing", "shows", "gate", "reason", "question"),
)
PRICES = {"opus": (15.0, 75.0), "sonnet": (3.0, 15.0), "haiku": (1.0, 5.0)}
"""100만 토큰당 달러(입력, 출력). 보수 단가다. 모르는 모델은 opus 값으로 센다. 캐시 쓰기는 입력의 1.25배, 읽기는
0.1배."""
RESERVE = {"haiku": 0.15, "sonnet": 0.45, "opus": 2.0}
"""질문 하나를 새로 보내기 전에 남아 있어야 하는 어림 금액. 대화 중에는 멈출 수 없어 상한을 넘지 않게 미리 남긴다."""
MAX_TOKENS = 16000
"""답 하나의 출력 상한. 이해 단계의 흐름과 기능 묶음의 답이 8192 에서 잘렸다(11/11 실측). 쓴 만큼만 청구된다."""


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
    concurrency: int = 6
    batch: str = "duty"  # duty | feature. 11/11 실측(사례 4곳): duty 가 의무마다 인용이 많고 비용은 1.8배, 시간은 비슷


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


def _whenever() -> dict[str, str]:
    """그 기능이 있으면 걸리는 의무 → 기능 id (features.yaml 의 whenever)."""
    return {d: f["id"] for f in load_features()["features"] for d in f.get("whenever") or []}


def _goods() -> dict[str, dict]:
    """특정 품목을 팔 때만 걸리는 의무 → 그 품목(features.yaml 의 goods)."""
    return {d: g for g in load_features().get("goods") or [] for d in g["duties"]}


def core_key(d: dict) -> tuple:
    """기능 안에서 묻고 늘어놓는 순서: 품목 의무는 맨 뒤, 그 앞은 일반 범위 → 그 기능이 있으면 걸리는 의무(whenever) →
    흔한 것(의무 지도의 freq) → 확신 높은 것. 11/12 실측: id 순으로 물어 상한에 걸린 POS 가 농산물 원산지를 묻고
    탈퇴·해지(전자상거래법)는 묻지 못했다."""
    return (
        d["id"] in _goods(),
        d["scope"] != "general",
        d["id"] not in _whenever(),
        -(d.get("freq") or 0),
        d["confidence"] != "high",
        d["id"],
    )


def _present(feature: dict | None) -> bool:
    return feature is not None and "removed" not in feature


def _feature_citations(root: Path, feature: dict) -> list[dict]:
    """기능이 있다는 근거를 인용 꼴로(why: profile). 이해 단계의 인용(관문 통과)이 먼저, 다음이 프로필 신호의 줄이다."""
    out = [c for c in feature.get("model_citations", []) if c.get("ok")]
    for e in feature.get("evidence", []):
        text = ""
        if e.get("line"):
            with suppress(OSError, IndexError):
                text = (root / e["file"]).read_text(encoding="utf-8", errors="replace").splitlines()[e["line"] - 1]
        out.append({"file": e["file"], "line": e.get("line"), "text": text.strip()[:200], "ok": True, "why": "profile"})
    return out[:2]


def said(r: dict) -> dict:
    """답이 적은 걸리는 조건(applies·condition), 없는 것(missing), 충족 인용의 성격(shows)."""
    return {
        "applies": r.get("applies") if r.get("applies") in P.APPLIES else None,
        "condition": str(r.get("condition") or "").strip()[:300],
        "missing": str(r.get("missing") or "").strip()[:300],
        "shows": r.get("shows") if r.get("shows") in P.SHOWS else None,
    }


def absent(d: dict, s: dict, proven: bool, feature: dict | None, cited: bool) -> tuple[str, dict | None]:
    """'해당 없음'은 걸리는 조건 자체가 없을 때만 받는다(11/12 실측: '약관이 아예 없다', '탈퇴 경로가 아예 없다',
    '위치 동의 철회 기능이 없다'를 해당 없음으로 읽었다 — 검색 관문은 줄 수만 맞춰 봐서 막지 못했다).
    (상태, 관문이 바꾼 까닭 또는 None)"""
    if d["id"] in _whenever() and _present(feature):
        note = f"{feature['name']} 기능이 있으면 걸리는 의무라 '해당 없음'으로 받지 않았습니다"
        note += ". 지킨 처리는 찾지 못했습니다"
        return "seen-in-code", {"from": "not-applicable", "why": "condition-present", "note": _missing(note, s)}
    if s["applies"] == "예":
        note = "걸리는 조건이 있다고 답해" + (f"({s['condition']})" if s["condition"] else "")
        note += " '해당 없음'으로 받지 않았습니다. 지킨 처리는 찾지 못했습니다"
        gate_ = {"from": "not-applicable", "why": "condition-present", "note": _missing(note, s)}
        return ("seen-in-code" if cited else "check-applicability"), gate_
    if s["applies"] != "아니오" or not s["condition"]:
        note = "걸리는 조건 자체가 없다는 답(applies '아니오'와 condition)이 없어 '해당 없음'으로 받지 않았습니다."
        return "check-applicability", {"from": "not-applicable", "why": "no-condition", "note": note}
    return ("not-applicable" if proven else "likely-not-applicable"), None


def _missing(note: str, s: dict) -> str:
    return note + (f": {s['missing']}." if s["missing"] else ".")


def accept(d: dict, s: dict, answered: str, cs: list[dict], proven: bool, feature: dict | None):
    """모델이 고른 상태에 받는 조건을 건다. (상태, 관문이 바꾼 까닭 또는 None)"""
    if answered == "not-applicable":
        return absent(d, s, proven, feature, grounded(cs))
    if answered in ("evidence-found", "seen-in-code") and not grounded(cs):
        return "check-outside", None
    if answered == "evidence-found" and s["shows"] != "행위":
        # 11/12 실측: helmet 의 기본 HSTS 만으로 전송 암호화 충족, 메뉴의 'GenAI' 글자로 AI 사전 고지 충족
        note = "인용이 조문이 요구하는 행위가 아니라 이름·기본값뿐이라 '충족 근거 있음'으로 받지 않았습니다."
        return "seen-in-code", {"from": answered, "why": "name-or-default", "note": note}
    return answered, None


def prove(root: Path, searches: list[dict]) -> tuple[list[dict], bool]:
    """모델이 "찾아봤는데 없다"며 낸 검색을 저장소에서 다시 돌린다. 검색마다 {pattern, path, claimed, found, ok, why}.
    증명은 검색이 하나 이상이고 모두 줄 수가 같을 때다(why: match). 다르면 mismatch, 정규식이 틀리거나 두 글자보다
    짧으면 bad-pattern, 저장소 밖이면 outside-repo, 줄 수를 적지 않았으면 no-count 다."""
    tools, out = RepoTools(root), []
    for s in searches:
        pattern, path = str(s.get("pattern") or ""), str(s.get("path") or ".")
        claimed = s.get("hits") if isinstance(s.get("hits"), int) else None
        rec = {"pattern": pattern[:200], "path": path[:200], "claimed": claimed, "found": None, "ok": False, "why": ""}
        if len(pattern.strip()) < 2:
            rec["why"] = "bad-pattern"
        else:
            try:
                rec["found"] = tools.count(pattern, path)
            except re.error:
                rec["why"] = "bad-pattern"
            except ValueError:
                rec["why"] = "outside-repo"
        if rec["found"] is not None:
            rec["why"] = "no-count" if claimed is None else "match" if claimed == rec["found"] else "mismatch"
            rec["ok"] = rec["why"] == "match"
        out.append(rec)
    return out, bool(out) and all(r["ok"] for r in out)


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


def _platforms(prof: dict) -> str:
    return ", ".join(PLATFORM_KO[p] for p in prof.get("platforms", [])) or "알 수 없음(package.json 으로 가르지 못함)"


def understand(run: Run, prof: dict, catalog: dict[str, str]) -> dict:
    budget = 40
    prompt = P.UNDERSTAND.format(
        found=_found_lines(prof),
        platforms=_platforms(prof),
        catalog="\n".join(f"- {k}: {v}" for k, v in catalog.items()),
        budget=budget,
        cite=P.CITE,
        rules=P.RULES,
    )
    doc, _, _ = run.ask("understand", run.investigator, prompt, budget, {}, "summary")
    return _understood(run.root, doc, catalog)


def _understood(root: Path, doc: dict | None, catalog: dict[str, str], reused: bool = False) -> dict:
    """이해 단계의 답(또는 앞 결과에서 되살린 같은 꼴)을 관문에 건다."""
    out = {"summary": "", "added": [], "removed": [], "nodes": [], "edges": [], "rejected_claims": 0, "answered": False}
    out["reused"] = reused
    if doc is None:
        return out
    out["answered"] = True
    out["summary"] = str(doc.get("summary") or "")[:800]
    for key, dest in (("features_added", "added"), ("features_removed", "removed")):
        for item in doc.get(key) or []:
            if not isinstance(item, dict) or item.get("feature") not in catalog:
                continue
            cs = check(root, P.citations_of(item))
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
        cs = check(root, P.citations_of(n))
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
        cs = check(root, P.citations_of(e))
        if not grounded(cs):
            out["rejected_claims"] += 1
            continue
        out["edges"].append(
            {"from": e["from"], "to": e["to"], "data": [str(x)[:40] for x in e.get("data") or []][:12], "citations": cs}
        )
    return out


def from_previous(root: Path, prev: dict, catalog: dict[str, str]) -> dict:
    """앞 review 결과(같은 저장소·커밋)의 이해 단계 결과를 되살린다. 인용은 지금 저장소에서 관문에 다시 건다."""
    prof = prev.get("profile") or {}
    flow = prev.get("data_flow") or {}
    doc = {
        "summary": prof.get("summary", ""),
        "features_added": [
            {"feature": f["id"], "citations": f.get("model_citations", []), "reason": f.get("model_reason", "")}
            for f in prof.get("features", [])
            if "model" in f.get("sources", [])
        ],
        "features_removed": [
            {"feature": f["id"], **f["removed"]} for f in prof.get("features", []) if isinstance(f.get("removed"), dict)
        ],
        "flow": {"nodes": flow.get("nodes", []), "edges": flow.get("edges", [])},
    }
    return _understood(root, doc, catalog, reused=True)


def commit_of(root: Path) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


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


def investigate(
    run: Run, group: list[dict], feature: dict | None, summary: str, static: dict, platforms: str
) -> dict[str, dict]:
    budget = _budget(len(group), 20, 3, 40)
    prompt = P.INVESTIGATE.format(
        summary=summary or "(이해 단계의 요약 없음)",
        platforms=platforms,
        evidence=_evidence_lines(feature),
        static=_static_lines(group, static),
        duties="\n".join(P.duty_block(d) for d in group),
        budget=budget,
        cite=P.CITE,
        search=P.SEARCH,
        condition=P.CONDITION,
        act=P.ACT,
        absence=P.ABSENCE,
        rules=P.RULES,
    )
    meta = {"feature": group[0]["feature"], "duties": [d["id"] for d in group]}
    doc, failure, qn = run.ask("investigate", run.investigator, prompt, budget, meta, "results")
    results: dict[str, dict] = {}
    if failure in ("cost-cap", "time-cap") and doc is None and not run.questions[qn].get("calls"):
        return {d["id"]: {"asked": False, "why": failure, "q": qn} for d in group}
    by_id = {d["id"]: d for d in group}
    for r in (doc or {}).get("results") or []:
        if not isinstance(r, dict) or r.get("duty") not in by_id or r.get("status") not in P.ANSWER:
            continue
        answered = P.ANSWER[r["status"]]
        cs = check(run.root, P.citations_of(r))
        searches, proven = prove(run.root, P.searches_of(r))
        s = said(r)
        status, gate_ = accept(by_id[r["duty"]], s, answered, cs, proven, feature)
        if status == "seen-in-code" and not grounded(cs):
            cs = cs + _feature_citations(run.root, feature)  # 조건(기능)이 있다는 근거는 프로필 신호다
        reason = str(r.get("reason") or "")[:800]
        results[r["duty"]] = {
            "asked": True,
            "status": status,
            "answered": answered,
            "citations": cs,
            "searches": searches,
            **s,
            "gate": gate_,
            "question": str(r.get("question") or "")[:400],
            "reason": f"{gate_['note']} {reason}".strip() if gate_ else reason,
            "q": qn,
        }
    for d in group:
        if d["id"] not in results:
            results[d["id"]] = {"asked": True, "why": failure or "no-answer", "q": qn}
    return results


def rebut(
    run: Run, group: list[dict], first: dict[str, dict], summary: str, platforms: str, feature: dict | None = None
) -> dict[str, dict]:
    items = [d for d in group if first.get(d["id"], {}).get("status") in (*DROPS, *TO_CHECK)]
    if not items:
        return {}
    budget = _budget(len(items), 15, 3, 35)
    blocks = []
    for d in items:
        f = first[d["id"]]
        ok = [c for c in f["citations"] if c["ok"]]
        blocks.append(
            P.duty_block(d)
            + f"\n  앞 판단: {P.SAID[f['status']]} — {f['reason']}"
            + (f"\n  앞 판단의 걸리는 조건: {f['condition']} ({f['applies'] or '?'})" if f.get("condition") else "")
            + (f"\n  앞 판단이 적은 없는 것: {f['missing']}" if f.get("missing") else "")
            + (f"\n  앞 인용: {P.cite_lines(ok)}" if ok else "")
            + (f"\n  앞 검색: {P.search_lines(f['searches'])}" if f["searches"] else "")
        )
    prompt = P.REBUT.format(
        summary=summary or "(요약 없음)",
        platforms=platforms,
        items="\n".join(blocks),
        budget=budget,
        cite=P.CITE,
        search=P.SEARCH,
        condition=P.CONDITION,
        act=P.ACT,
        absence=P.ABSENCE,
        rules=P.RULES,
    )
    meta = {"feature": group[0]["feature"], "duties": [d["id"] for d in items]}
    doc, failure, qn = run.ask("rebut", run.checker, prompt, budget, meta, "results")
    if failure in ("cost-cap", "time-cap") and doc is None and not run.questions[qn].get("calls"):
        return {d["id"]: {"result": "not-run", "why": failure, "q": qn} for d in items}
    out: dict[str, dict] = {}
    by_id = {d["id"]: d for d in items}
    for r in (doc or {}).get("results") or []:
        if not isinstance(r, dict) or r.get("duty") not in by_id or r.get("result") not in ("유지", "뒤집음"):
            continue
        cs = check(run.root, P.citations_of(r))
        searches, proven = prove(run.root, P.searches_of(r))
        s = said(r)
        rec = {
            "citations": cs,
            "searches": searches,
            **s,
            "gate": None,
            "off_quote": r.get("off_quote") is True,
            "reason": str(r.get("reason") or "")[:800],
            "q": qn,
        }
        before = first[r["duty"]]["status"]
        claimed = P.ANSWER.get(r.get("status") or "", "")
        if r["result"] == "유지" or (before in TO_CHECK and claimed not in ("evidence-found", "not-applicable")):
            out[r["duty"]] = {"result": "upheld", **rec}
            continue
        # 빼는 답을 깨면 '코드에서 본 것'(인용 필요). 확인할 것을 깨면 충족(행위 자체를 보이는 인용) 또는 해당
        # 없음(걸리는 조건이 없다는 답과 검색 증명)이다. 해당 없음은 조사 답과 같은 관문(absent)을 넘어야 받는다
        if before in DROPS:
            after, ok = "seen-in-code", grounded(cs)
        elif claimed == "evidence-found":
            after, ok = claimed, grounded(cs) and s["shows"] == "행위"
        else:
            got, rec["gate"] = absent(by_id[r["duty"]], s, proven, feature, grounded(cs))
            after, ok = claimed, got == "not-applicable"
        out[r["duty"]] = {"result": "overturned" if ok else "overturn-ungrounded", "status": after, **rec}
    for d in items:
        out.setdefault(d["id"], {"result": "not-run", "why": failure or "no-answer", "q": qn})
    return out


def _base(d: dict, static: list[dict]) -> dict:
    return {
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


def _goods_item(d: dict, g: dict) -> dict:
    """품목 신호가 없어 묻지 않은 품목 의무. '해당 여부부터 확인할 것'의 맨 뒤에 한 묶음(group: goods)으로 싣는다."""
    return {
        **_base(d, []),
        "status": "check-applicability",
        "asked": False,
        "not_answered": "goods-not-detected",
        "group": "goods",
        "first": None,
        "verification": {"result": "not-run", "why": "goods-not-detected"},
        "citations": [],
        "searches": [],
        "question": f"{g['name']}도 판매하나요? 판매한다면 이 의무가 걸립니다.",
        "reason": f"{g['name']} 판매에만 걸리는 의무입니다. 코드에서 이 품목의 신호를 찾지 못해 묻지 않았습니다.",
    }


def _item(d: dict, first: dict, check_: dict | None, static: list[dict]) -> dict:
    base = _base(d, static)
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
            "searches": [],
            "question": "",
            "reason": NOT_ANSWERED.get(why, "답을 받지 못했습니다"),
        }
    status, citations, searches = first["status"], first["citations"], first["searches"]
    why = "business-judgment" if status == "check-applicability" else "no-answer"
    verification = {"result": "not-run", "why": why}
    overturned = bool(check_) and check_["result"] == "overturned"
    if check_:
        verification = {k: v for k, v in check_.items() if k != "q"}
        if overturned:
            status, citations, searches = check_["status"], check_["citations"], check_["searches"]
    return {
        **base,
        "status": status,
        "asked": True,
        "first": {k: first[k] for k in FIRST_KEYS},
        "verification": verification,
        "citations": citations,
        "searches": searches,
        "missing": verification.get("missing", "") if overturned else first["missing"],
        "question": first["question"],
        "reason": first["reason"] if status == first["status"] else verification.get("reason", ""),
    }


def arrange(checklist: list[dict]) -> list[dict]:
    """갈래 순(prompts.ORDER), 그 안에서는 묻지 않은 품목 묶음이 맨 뒤, 그 앞은 PRIORITY·기능 목록 순, 기능 안에서는
    핵심 의무 순(core_key). rank·status_label 을 붙인다."""
    feats = [*PRIORITY, *(f["id"] for f in load_features()["features"] if f["id"] not in PRIORITY)]
    pos = {f: i for i, f in enumerate(feats)}
    rows = {d["id"]: d for d in load_duties()}

    def key(c: dict) -> tuple:
        row = rows.get(c["duty"])
        core = core_key(row) if row else (False, True, True, 0, True, c["duty"])
        return (P.ORDER.index(c["status"]), c.get("group") == "goods", pos.get(c["feature"], 99), *core)

    out = sorted(checklist, key=key)
    for i, c in enumerate(out, 1):
        c["rank"], c["status_label"] = i, P.STATUS_LABEL[c["status"]]
    return out


# ── 전체 ─────────────────────────────────────────────────────────────


def _blank(fid: str, name: str) -> dict:
    return {"id": fid, "name": name, "sources": [], "evidence": [], "evidence_total": 0, "model_citations": []}


def select(prof: dict, und: dict, static: dict[str, list[dict]]) -> tuple[list[dict], ...]:
    """(기능 목록, 목록 층 의무, 검토 층 의무, 묻지 않는 품목 의무). 기능은 신호 + 이해 단계가 더한 것 − 뺀 것 + 정적
    검사가 찾은 것. 검토 층은 묻는 순서다(PRIORITY·기능 목록 순, 기능 안에서는 core_key). 품목 의무는 프로필에 그
    품목 신호가 있을 때만 묻는다."""
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
    goods, seen = _goods(), {g["id"] for g in prof.get("goods") or []}
    skipped = [d for d in review if d["id"] in goods and goods[d["id"]]["id"] not in seen]
    review = [d for d in review if d not in skipped]
    review.sort(key=lambda d: (order.get(d["feature"], rest.get(d["feature"], 99)), *core_key(d)))
    return list(features.values()), listed, review, skipped


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
    features, listed, review, skipped = select(prof, empty, static)
    return {
        "features": [f["id"] for f in features],
        "listed": len(listed),
        "review": len(review),
        "goods_not_asked": len(skipped),
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
    reuse: dict | None = None,
) -> dict:
    """`reuse` 는 같은 저장소·커밋의 앞 review 결과다. 주면 이해 단계를 묻지 않고 그 결과를 쓴다."""
    limits = limits or Limits()
    root = root.resolve()
    t0 = time.monotonic()
    for j in (investigator, checker):
        j.deadline = t0 + limits.seconds
    run = Run(root, investigator, checker, limits, Spend(limits.usd), t0=t0)

    prof = profile(root)
    static, static_err = static_results(root) if use_static else ({}, None)
    catalog = {f["id"]: f["name"] for f in load_features()["features"]}
    und = from_previous(root, reuse, catalog) if reuse is not None else understand(run, prof, catalog)
    features, listed, review_duties, skipped = select(prof, und, static)
    by_feature = {f["id"]: f for f in features}
    groups = groups_of(review_duties, limits.batch)
    plats = _platforms(prof)

    def work(group: list[dict]) -> tuple[dict, dict]:
        feature = by_feature.get(group[0]["feature"])
        first = investigate(run, group, feature, und["summary"], static, plats)
        return first, rebut(run, group, first, und["summary"], plats, feature)

    firsts: dict[str, dict] = {}
    checks: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max(1, limits.concurrency)) as pool:
        for first, chk in pool.map(work, groups):
            firsts |= first
            checks |= chk

    goods = _goods()
    checklist = arrange(
        [_item(d, firsts.get(d["id"], {}), checks.get(d["id"]), static.get(d["id"], [])) for d in review_duties]
        + [_goods_item(d, goods[d["id"]]) for d in skipped]
    )
    seconds = time.monotonic() - t0
    return _report(run, prof, und, features, listed, checklist, static, static_err, seconds, throttles)


def _report(run: Run, prof, und, features, listed, checklist, static, static_err, seconds, throttles) -> dict:
    in_checklist = {c["duty"] for c in checklist}
    # 모델이 댄 인용만 센다(조건의 근거로 붙인 프로필 신호 why: profile 은 빼고)
    cites = [c for q in checklist for c in (q["first"] or {}).get("citations", []) if c["why"] != "profile"]
    searches = [s for q in checklist for s in (q["first"] or {}).get("searches", [])]
    searches += [s for q in checklist for s in q["verification"].get("searches", [])]
    cites += [c for q in checklist for c in q["verification"].get("citations", [])]
    for part in ("nodes", "edges"):
        cites += [c for x in und[part] for c in x["citations"]]
    masked: dict[str, int] = {}
    refused: set[str] = set()
    for q in run.questions:
        for k, v in (q.get("sent") or {}).get("masked", {}).items():
            masked[k] = masked.get(k, 0) + v
        refused |= set((q.get("sent") or {}).get("refused", []))
    counts = {s: sum(1 for c in checklist if c["status"] == s) for s in P.ORDER}
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
        "summary": {
            "counts": counts,
            "labels": P.STATUS_LABEL,
            "top": [c["duty"] for c in checklist[:5]],
            "groups": [
                {"id": "goods", "label": GOODS_LABEL, "status": "check-applicability", "duties": goods}
                for goods in [[c["duty"] for c in checklist if c.get("group") == "goods"]]
                if goods
            ],
        },
        "profile": {
            "commit": commit_of(run.root),
            "platforms": prof["platforms"],
            "summary": und["summary"],
            "features": features,
            "test_only": prof["test_only"],
            "goods": prof.get("goods", []),
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
            # 부재 주장의 검색. 관문이 다시 돌려 줄 수가 다른 것(mismatch 등)이 rejected 다
            "searches": len(searches),
            "searches_rejected": sum(1 for s in searches if not s["ok"]),
            "understanding": {
                "answered": und["answered"],
                "rejected_claims": und["rejected_claims"],
                "reused": und["reused"],
            },
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
