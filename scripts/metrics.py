#!/usr/bin/env python3
"""scan 의 JSON 보고서에서 정답 없이 셀 수 있는 지표를 모은다. 모델을 부르지 않는다.

    python scripts/metrics.py RUNS/*.json            # 저장소마다 한 줄 + 합계 (Markdown 표)
    python scripts/metrics.py RUNS/ --json           # 같은 것을 JSON 으로

지표(결과 보고서에 싣는 것, docs/decisions/0004)
  경고        검토 필요 · 불확실 수(findings[].outcome)
  인용 관문   에이전트가 낸 인용 가운데 관문이 거절한 수와 비율
              (코드에 글자 그대로 없거나, 진입 파일 밖이거나, 저장소 밖)
  해제        에이전트가 인용으로 푼 경고(cleared), 정적 경고를 확인한 것(confirmed), 새로 찾은 경고(warned)
  외부 전송   에이전트가 읽었거나 검색 결과로 줄이 나간 파일 수, 읽기를 거절한 비밀 파일 수, 가린 비밀값 수(종류별),
              답을 받지 못한 질문
  비용        모델 호출, 토큰, 어림 금액(보수 단가: 아래 PRICES, 100만 토큰당 달러), 정적 검사 시간

어림 금액은 캐시 쓰기를 입력 단가의 1.25배, 캐시 읽기를 0.1배로 센다. 청구액은 Console 이 맞다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PRICES = {"opus": (15.0, 75.0), "sonnet": (3.0, 15.0), "haiku": (1.0, 5.0)}
STAGES = ("", "discover", "recheck")


def usd(usage: dict, judge_id: str) -> float:
    pin, pout = next((v for k, v in PRICES.items() if k in judge_id), PRICES["opus"])
    return (
        usage.get("input_tokens", 0) * pin
        + usage.get("cache_creation_input_tokens", 0) * pin * 1.25
        + usage.get("cache_read_input_tokens", 0) * pin * 0.1
        + usage.get("output_tokens", 0) * pout
    ) / 1e6


def stages(agent: dict) -> list[dict]:
    """review(또는 independent) 단계와 그 뒤의 찾기·재확인 단계."""
    return [agent] + [agent[s] for s in STAGES[1:] if agent.get(s)]


def one(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    run = doc.get("run", {})
    outcomes = Counter(f["outcome"] for f in doc.get("findings", []))
    row = {
        "repo": path.stem,
        "files": run.get("files", 0),
        "needs_review": outcomes.get("needs-review", 0),
        "uncertain": outcomes.get("needs-review-uncertain", 0),
        "static_seconds": run.get("static_seconds") or 0.0,
        "agent": False,
        "masked": dict(run.get("judge_masked") or {}),
    }
    agent = run.get("agent")
    if not agent:
        return row
    actions: Counter = Counter()
    masked: Counter = Counter(row["masked"])
    read: set[str] = set()
    refused: set[str] = set()
    cites = rejected = unanswered = calls = 0
    tokens_in = tokens_out = 0
    cost = 0.0
    for st in stages(agent):
        actions.update(st.get("actions", {}))
        cites += st.get("citations", 0)
        rejected += st.get("citations_rejected", 0)
        for q in st.get("questions", []):
            unanswered += bool(q.get("failure"))
            sent = q.get("sent") or {}
            read.update(sent.get("read", []), sent.get("matched", []))
            refused.update(sent.get("refused", []))
            masked.update(sent.get("masked", {}))
        u = st.get("usage", {})
        calls += st.get("model_calls", 0)
        tokens_in += sum(
            u.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        )
        tokens_out += u.get("output_tokens", 0)
        cost += usd(u, st.get("judge", ""))
    row.update(
        agent=True,
        mode=agent.get("mode", "review"),
        cleared=actions.get("cleared", 0),
        confirmed=actions.get("confirmed", 0),
        warned=actions.get("warned", 0) + actions.get("warned-uncertain", 0),
        citations=cites,
        citations_rejected=rejected,
        unanswered=unanswered,
        skipped=agent.get("questions_skipped", 0),
        files_read=len(read),
        refused=len(refused),
        masked=dict(masked),
        model_calls=calls,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        usd=round(cost, 4),
    )
    return row


def total(rows: list[dict]) -> dict:
    t: dict = {"repo": f"합계 {len(rows)}곳", "masked": Counter()}
    for r in rows:
        for k, v in r.items():
            if k == "masked":
                t["masked"].update(v)
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                t[k] = t.get(k, 0) + v
    t["masked"] = dict(t["masked"])
    t["agent"] = any(r["agent"] for r in rows)
    return t


def rate(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.0%})" if d else "-"


def table(rows: list[dict]) -> str:
    agent = any(r["agent"] for r in rows)
    head = ["저장소", "파일", "검토 필요", "불확실", "정적 초"]
    if agent:
        head += [
            "해제",
            "확인",
            "새 경고",
            "인용 거절",
            "못 받은 답",
            "나간 파일",
            "거절한 비밀 파일",
            "가림",
            "호출",
            "입력 토큰",
            "출력 토큰",
            "어림 $",
        ]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in [*rows, total(rows)]:
        cells = [r["repo"], r["files"], r["needs_review"], r["uncertain"], f"{r['static_seconds']:.1f}"]
        if agent:
            cells += [
                r.get("cleared", 0),
                r.get("confirmed", 0),
                r.get("warned", 0),
                rate(r.get("citations_rejected", 0), r.get("citations", 0)),
                r.get("unanswered", 0),
                r.get("files_read", 0),
                r.get("refused", 0),
                sum(r.get("masked", {}).values()),
                r.get("model_calls", 0),
                f"{r.get('tokens_in', 0):,}",
                f"{r.get('tokens_out', 0):,}",
                f"{r.get('usd', 0):.2f}",
            ]
        out.append("| " + " | ".join(map(str, cells)) + " |")
    t = total(rows)
    if t["masked"]:
        out.append("")
        out.append("가린 비밀값(종류별): " + ", ".join(f"{k} {v}" for k, v in sorted(t["masked"].items())))
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+", type=Path, help="scan --output-format json 보고서, 또는 그것이 든 폴더")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    files = sorted(f for p in a.paths for f in (p.glob("*.json") if p.is_dir() else [p]))
    rows = []
    for f in files:
        try:
            rows.append(one(f))
        except (json.JSONDecodeError, KeyError) as e:
            print(f"건너뜀 {f}: {e}", file=sys.stderr)
    if not rows:
        sys.exit("보고서가 없다")
    if a.json:
        print(json.dumps({"rows": rows, "total": total(rows)}, ensure_ascii=False, indent=1))
    else:
        print(table(rows))


if __name__ == "__main__":
    main()
