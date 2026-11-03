#!/usr/bin/env python3
"""LLM 라벨러를 부른다. 단위마다 라벨러 모델이 읽기 전용 도구로 저장소를 읽고 JSON 답 하나를 낸다.

    ANTHROPIC_API_KEY=... label.py --repos DIR --units units.json --model claude-opus-5-5 --labeler A \
        --out OUTDIR [--max-usd 5] [--workers 4] [--only N]

  DIR        저장소마다 폴더 하나(<owner>__<name>). units.json 의 file 은 "<폴더>/<저장소 안 경로>"
  units.json units.py 의 출력. [{file, policy, source}]. adjudicate.py 의 disputes.json 을 주면 조정자로 돈다
             (두 라벨러의 답을 지시문 끝에 붙인다. 판정 기준은 같다)
  OUTDIR     단위마다 기록 하나(raw/<번호>.json: 보낸 것·받은 것 전부, 사용량), labels.jsonl(채점용 한 줄씩)

지시문은 guide/labeller-prompt.md 에 정책 절(guide/LABEL_GUIDE.md 의 "## 정책 <id>" 부터 다음 "## 정책" 앞까지)을
넣은 것이다. 받은 그대로 쓰고 고치지 않는다. API 는 표준 라이브러리로 부른다(SDK 설치 없이).

지키는 것
  - 도구는 셋(list_files, read_file, search)이고 저장소 폴더 밖을 읽지 못한다. 쓰기·실행·네트워크 도구는 없다.
  - 단위당 도구 호출 30번. 넘으면 도구 결과 대신 "예산 끝"을 돌려주고, 다음 요청은 도구 없이 답만 받는다.
  - 비용 상한(--max-usd): 이 출력 폴더에서 사용량으로 어림한 누적 금액(앞선 실행 포함)이 상한에 닿으면 새 단위를
    시작하지 않는다. 이미 시작한 단위는 끝까지 간다. 단가는 보수적으로
    잡은 값(PRICES)이라 실제 청구액보다 크게 나온다. 실제 금액은 콘솔에서 본다.
  - 라벨러는 도구의 출력, 정책 팩, 판정기 프롬프트를 받지 않는다.
  - 인용은 저장소에서 그 줄을 다시 읽어 글자가 맞는지 확인하고 결과에 적는다(citations_ok). 값은 바꾸지 않는다.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import fnmatch
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUIDE = HERE.parent / "guide"
API = "https://api.anthropic.com/v1/messages"
BUDGET = 30
MAX_TURNS = 45
MAX_TOKENS = 2048
#: 백만 토큰당 달러 (입력, 출력). 실제보다 높게 잡은 값이다. 캐시 쓰기 1.25배, 캐시 읽기 0.1배.
PRICES = {"opus": (15.0, 75.0), "sonnet": (3.0, 15.0), "haiku": (1.0, 5.0)}
LABELS = {
    "검토 필요": "needs-review",
    "충족 근거 있음": "compliant",
    "해당 없음": "not-applicable",
    "가를 수 없음": "unsure",
}
SKIP_DIRS = {".git", "node_modules", "dist", "build", ".next", "out", "coverage", ".turbo", ".cache", "vendor"}
MAX_FILE_BYTES = 2_000_000
READ_LINES = 400
READ_CHARS = 40_000
SEARCH_HITS = 80

TOOLS = [
    {
        "name": "list_files",
        "description": "저장소의 파일 목록을 본다. path 는 저장소 루트 기준 폴더(기본 '.'), "
        "pattern 은 파일 경로에 맞출 glob(예: '*.tsx', '*terms*'). node_modules·.git·빌드 폴더는 빠진다. 최대 500개.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "pattern": {"type": "string"}},
        },
    },
    {
        "name": "read_file",
        "description": f"파일을 줄 번호와 함께 읽는다. start_line·end_line 은 1부터 센다. 한 번에 {READ_LINES}줄까지.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search",
        "description": "저장소에서 글자를 찾는다. pattern 은 대소문자를 가리지 않는 정규식(Python re). path 로 폴더를 "
        f"좁힐 수 있다. 결과는 '경로:줄: 내용' 꼴로 {SEARCH_HITS}개까지.",
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
            "required": ["pattern"],
        },
    },
]


# ── 도구 ─────────────────────────────────────────────────────────────


class Repo:
    """저장소 폴더 하나. 모든 경로는 이 폴더 안으로만 풀린다."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def path(self, rel: str | None) -> Path:
        p = (self.root / (rel or ".").lstrip("/")).resolve()
        if p != self.root and self.root not in p.parents:
            raise ValueError("저장소 밖의 경로다")
        return p

    def files(self, base: Path):
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for name in sorted(filenames):
                f = Path(dirpath) / name
                if f.is_symlink():
                    continue
                yield f

    def rel(self, p: Path) -> str:
        return p.relative_to(self.root).as_posix()

    def list_files(self, path: str = ".", pattern: str | None = None) -> str:
        out = []
        for f in self.files(self.path(path)):
            r = self.rel(f)
            if pattern and not (fnmatch.fnmatch(r, pattern) or fnmatch.fnmatch(f.name, pattern)):
                continue
            out.append(r)
            if len(out) >= 500:
                out.append("… (500개에서 자름)")
                break
        return "\n".join(out) or "(파일 없음)"

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> str:
        p = self.path(path)
        if not p.is_file():
            return "그런 파일이 없다"
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start_line or 1))
        end = min(len(lines), int(end_line) if end_line else start + READ_LINES - 1, start + READ_LINES - 1)
        body, size = [], 0
        for i in range(start, end + 1):
            row = f"{i}\t{lines[i - 1]}"
            size += len(row) + 1
            if size > READ_CHARS:
                body.append(f"… ({i}줄 앞에서 자름. start_line={i} 로 이어 읽는다)")
                break
            body.append(row)
        tail = f"\n(전체 {len(lines)}줄)" if end < len(lines) else ""
        return "\n".join(body) + tail

    def search(self, pattern: str, path: str = ".") -> str:
        try:
            rx = re.compile(pattern, re.I)
        except re.error as e:
            return f"정규식 오류: {e}"
        hits = []
        for f in self.files(self.path(path)):
            try:
                if f.stat().st_size > MAX_FILE_BYTES:
                    continue
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{self.rel(f)}:{i}: {line.strip()[:200]}")
                    if len(hits) >= SEARCH_HITS:
                        return "\n".join(hits) + f"\n… ({SEARCH_HITS}개에서 자름)"
        return "\n".join(hits) or "(찾은 것 없음)"

    def call(self, name: str, args: dict) -> str:
        try:
            if name == "list_files":
                return self.list_files(args.get("path") or ".", args.get("pattern"))
            if name == "read_file":
                return self.read_file(args["path"], args.get("start_line") or 1, args.get("end_line"))
            if name == "search":
                return self.search(args["pattern"], args.get("path") or ".")
            return f"없는 도구: {name}"
        except (ValueError, KeyError, OSError) as e:
            return f"도구 오류: {e}"

    def line(self, rel: str, n: int) -> str | None:
        try:
            p = self.path(rel)
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except (ValueError, OSError):
            return None
        return lines[n - 1] if 1 <= n <= len(lines) else None


# ── 지시문 ───────────────────────────────────────────────────────────


def policy_section(guide: str, policy: str) -> str:
    m = re.search(rf"^## 정책 {re.escape(policy)}\b.*?(?=^## 정책 |\Z)", guide, re.M | re.S)
    if not m:
        raise SystemExit(f"기준서에 정책 절이 없다: {policy}")
    return m.group(0).strip()


def prompt(template: str, guide: str, repo: str, start: str, policy: str) -> str:
    return (
        template.replace("{{POLICY_SECTION}}", policy_section(guide, policy))
        .replace("{{REPO}}", repo)
        .replace("{{START_FILE}}", start)
        .replace("{{POLICY_ID}}", policy)
    )


ADJUDICATE = """

## 조정: 앞선 두 라벨러의 답
이 단위는 두 라벨러의 답이 갈렸다. 두 답과 근거를 참고하되, 저장소를 직접 읽어 확인하고 위 기준대로 하나를 고른다.
어느 답을 따를지가 아니라 기준서가 정하는 값을 고른다. 답의 형식은 위와 같다.
{answers}"""


def disputed_block(u: dict) -> str:
    """adjudicate.py 가 낸 갈린 단위면 두 답을 붙인다. 보통 단위면 빈 글."""
    if not u.get("answers"):
        return ""
    lines = []
    for i, ans in enumerate(u["answers"], 1):
        cites = "; ".join(
            f"{c.get('file')}:{c.get('line')} {str(c.get('text', ''))[:120]}" for c in ans.get("citations") or []
        )
        lines.append(
            f"- 답 {i}: {ans.get('label_ko')} — {ans.get('reason') or ''}" + (f" (인용: {cites})" if cites else "")
        )
    return ADJUDICATE.format(answers="\n".join(lines))


# ── API ──────────────────────────────────────────────────────────────


class Api:
    def __init__(self, key: str, model: str) -> None:
        self.key, self.model = key, model
        self.temperature = True

    def send(self, messages: list, tools: bool) -> dict:
        body = {"model": self.model, "max_tokens": MAX_TOKENS, "messages": cached(messages)}
        if self.temperature:
            body["temperature"] = 0
        body["tools"] = TOOLS
        body["tool_choice"] = {"type": "auto"} if tools else {"type": "none"}
        for attempt in range(5):
            req = urllib.request.Request(
                API,
                data=json.dumps(body).encode(),
                headers={
                    "x-api-key": self.key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")
                if e.code == 400 and "temperature" in detail and "temperature" in body:
                    self.temperature = False  # 이 모델은 temperature 를 받지 않는다
                    body.pop("temperature", None)
                    continue
                if e.code in (429, 500, 502, 503, 529) and attempt < 4:
                    time.sleep(10 * (attempt + 1))
                    continue
                raise RuntimeError(f"HTTP {e.code}: {detail[:500]}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 4:
                    time.sleep(10 * (attempt + 1))
                    continue
                raise RuntimeError(f"연결 실패: {e}") from None
        raise RuntimeError("재시도 끝")


def cached(messages: list) -> list:
    """마지막 메시지의 마지막 블록에 캐시 표시를 단다. 대화가 길어져도 앞부분은 캐시에서 읽힌다."""
    out = json.loads(json.dumps(messages))
    last = out[-1]
    if isinstance(last["content"], str):
        last["content"] = [{"type": "text", "text": last["content"]}]
    last["content"][-1]["cache_control"] = {"type": "ephemeral"}
    return out


def price(model: str, usage: dict) -> float:
    pin, pout = next((v for k, v in PRICES.items() if k in model), PRICES["opus"])
    return (
        usage.get("input_tokens", 0) * pin
        + usage.get("cache_creation_input_tokens", 0) * pin * 1.25
        + usage.get("cache_read_input_tokens", 0) * pin * 0.1
        + usage.get("output_tokens", 0) * pout
    ) / 1e6


# ── 단위 하나 ────────────────────────────────────────────────────────


def parse(text: str) -> dict | None:
    """답에서 "label" 을 가진 JSON 객체 하나를 찾는다. 앞뒤 글이 붙어 있어도 된다."""
    dec = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            doc, _ = dec.raw_decode(text, start)
        except json.JSONDecodeError:
            doc = None
        if isinstance(doc, dict) and "label" in doc:
            return doc
        start = text.find("{", start + 1)
    return None


def label_unit(api: Api, repo: Repo, text: str) -> dict:
    messages: list = [{"role": "user", "content": text}]
    calls, turns, usage, log = 0, 0, {}, []
    answer_text = ""
    while turns < MAX_TURNS:
        turns += 1
        tools_on = calls < BUDGET
        resp = api.send(messages, tools_on)
        log.append({"stop_reason": resp.get("stop_reason"), "usage": resp.get("usage"), "content": resp["content"]})
        for k, v in (resp.get("usage") or {}).items():
            if isinstance(v, int):
                usage[k] = usage.get(k, 0) + v
        messages.append({"role": "assistant", "content": resp["content"]})
        uses = [b for b in resp["content"] if b.get("type") == "tool_use"]
        if not uses:
            answer_text = "".join(b.get("text", "") for b in resp["content"] if b.get("type") == "text")
            break
        results = []
        for b in uses:
            calls += 1
            if calls > BUDGET:
                out = "도구 예산(30번)을 다 썼다. 더 찾지 말고 지금까지 본 것으로 JSON 답 하나만 하라."
            else:
                out = repo.call(b["name"], b.get("input") or {})
            results.append({"type": "tool_result", "tool_use_id": b["id"], "content": out})
        messages.append({"role": "user", "content": results})
    return {"answer_text": answer_text, "tool_calls": calls, "turns": turns, "usage": usage, "log": log}


def check_citations(repo: Repo, cites: list) -> list:
    out = []
    for c in cites or []:
        try:
            got = repo.line(str(c["file"]), int(c["line"]))
        except (KeyError, TypeError, ValueError):
            got = None
        want = str(c.get("text", "")).strip() if isinstance(c, dict) else ""
        out.append(bool(got is not None and want and want == got.strip()))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repos", type=Path, required=True)
    ap.add_argument("--units", type=Path, required=True)
    ap.add_argument("--model", required=True, help="전체 모델 id")
    ap.add_argument("--labeler", required=True, help="라벨러 이름(A, B, adj)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-usd", type=float, required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--only", type=int, help="앞에서부터 이만큼만")
    ap.add_argument("--reparse", action="store_true", help="모델을 부르지 않고 저장한 응답에서 결과를 다시 만든다")
    a = ap.parse_args()
    if a.reparse:
        reparse(a.out, a.repos)
        return
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("ANTHROPIC_API_KEY 가 없다")

    template = (GUIDE / "labeller-prompt.md").read_text(encoding="utf-8")
    guide = (GUIDE / "LABEL_GUIDE.md").read_text(encoding="utf-8")
    units = json.loads(a.units.read_text(encoding="utf-8"))[: a.only]
    (a.out / "raw").mkdir(parents=True, exist_ok=True)
    api = Api(key, a.model)
    lock, spent = threading.Lock(), [0.0]
    done_file = a.out / "labels.jsonl"
    done = set()
    if done_file.exists():
        rows = [json.loads(line) for line in done_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        done = {r["n"] for r in rows if r["label"] and not r["error"]}  # 실패한 단위는 다시 돈다
        spent[0] = sum(r["usd_estimate"] for r in rows)  # 상한은 이 폴더의 누적 금액에 건다

    def work(n: int, u: dict) -> None:
        with lock:
            if spent[0] >= a.max_usd:
                return
        folder, rel = u["file"].split("/", 1)
        repo = Repo(a.repos / folder)
        text = prompt(template, guide, folder.replace("__", "/", 1), rel, u["policy"]) + disputed_block(u)
        t0 = time.time()
        try:
            res = label_unit(api, repo, text)
            error = None
        except RuntimeError as e:
            res, error = {"answer_text": "", "tool_calls": 0, "turns": 0, "usage": {}, "log": []}, str(e)
        cost = price(a.model, res["usage"])
        row = make_row(n, u, a.labeler, a.model, repo, res, error, cost, time.time() - t0)
        raw = {**row, "prompt": text, "answer_text": res["answer_text"], "log": res["log"]}
        (a.out / "raw" / f"{n:05d}.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
        with lock:
            spent[0] += cost
            with open(done_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(
                f"[{n:3}] {row['label'] or '답 없음':15} 도구 {row['tool_calls']:2} 턴 {row['turns']:2} "
                f"${cost:.3f} (누적 ${spent[0]:.2f}) {u['policy']} {u['file']}" + (f" 오류 {error}" if error else ""),
                flush=True,
            )

    with cf.ThreadPoolExecutor(a.workers) as ex:
        futures = [ex.submit(work, n, u) for n, u in enumerate(units) if n not in done]
        for f in futures:
            f.result()
    print(f"끝. 어림 금액 ${spent[0]:.2f} (보수적 단가, 상한 ${a.max_usd})")


def make_row(n, u, labeler, model, repo, res, error, cost, seconds) -> dict:
    doc = parse(res["answer_text"]) or {}
    return {
        "n": n,
        "file": u["file"],
        "policy": u["policy"],
        "source": u.get("source"),
        "labeler": labeler,
        "model": model,
        "label": LABELS.get(doc.get("label")),
        "label_ko": doc.get("label"),
        "scope": None if doc.get("scope") in (None, "없음") else doc.get("scope"),
        "disputed": doc.get("disputed"),
        "reason": doc.get("reason"),
        "citations": doc.get("citations") or [],
        "citations_ok": check_citations(repo, doc.get("citations")),
        "parse_failed": not doc,
        "error": error,
        "tool_calls": res["tool_calls"],
        "turns": res["turns"],
        "usage": res["usage"],
        "usd_estimate": round(cost, 4),
        "seconds": round(seconds, 1),
    }


def reparse(out: Path, repos: Path) -> None:
    """저장해 둔 원 응답에서 labels.jsonl 을 다시 만든다. 모델을 부르지 않는다."""
    rows = []
    for f in sorted((out / "raw").glob("*.json")):
        raw = json.loads(f.read_text(encoding="utf-8"))
        res = {k: raw[k] for k in ("answer_text", "tool_calls", "turns", "usage")}
        repo = Repo(repos / raw["file"].split("/", 1)[0])
        u = {"file": raw["file"], "policy": raw["policy"], "source": raw.get("source")}
        row = make_row(
            raw["n"], u, raw["labeler"], raw["model"], repo, res, raw["error"], raw["usd_estimate"], raw["seconds"]
        )
        rows.append(row)
        f.write_text(json.dumps({**raw, **row}, ensure_ascii=False, indent=1), encoding="utf-8")
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    (out / "labels.jsonl").write_text(text, encoding="utf-8")
    print(f"다시 읽음 {len(rows)}개 · 답 없음 {sum(1 for r in rows if not r['label'])}개")


if __name__ == "__main__":
    main()
