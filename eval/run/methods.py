#!/usr/bin/env python3
"""네 방식(M1~M4)을 대기열 순서로 돌린다. 모델을 부르는 방식은 ANTHROPIC_API_KEY 가 필요하다.

    methods.py --queue draw.json --repos DIR --out RUNS --model claude-haiku-5-5 --max-usd 40 \
        [--methods M1,M2,M3,M4] [--recheck-model claude-sonnet-5-5] [--limit N]

  draw.json   eval/scripts/draw.py 의 출력. queue 의 순서대로 돈다(PROTOCOL.md 5절)
  DIR         저장소마다 폴더 하나(<owner>__<name>)
  RUNS        방식마다 폴더(RUNS/M1/<저장소>.json …), RUNS/LOG.tsv, RUNS/prefix.json

방식
  M1  scan --judge none
  M2  scan --judge anthropic:<모델>                           (정적으로 결론이 안 난 곳만 파일 하나를 보여 주고 묻는다)
  M3  scan --agent anthropic:<모델> --agent-mode independent  (정적 검사 없이)
  M4  scan --agent anthropic:<모델> --agent-mode combined     (review + 찾기 + 찾은 곳 재확인)

비용 상한: 보고서의 사용량(run.judge_usage, run.agent.total_usage, recheck_total_usage)을 보수 단가로 어림해 더한다.
누계가 상한에 닿으면 새 저장소를 시작하지 않는다. 네 방식을 모두 마친 저장소만 prefix.json 에 넣고, 채점은 그
앞부분만 쓴다(대기열 순서가 난수라 무작위 부분표본이다). 이미 결과가 있는 (방식, 저장소)는 다시 돌리지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PRICES = {"opus": (15.0, 75.0), "sonnet": (3.0, 15.0), "haiku": (1.0, 5.0)}
BIN = Path(__file__).resolve().parents[2] / ".venv" / "bin" / "policypack"


def usd(usage: dict, model: str) -> float:
    pin, pout = next((v for k, v in PRICES.items() if k in model), PRICES["opus"])
    return (
        usage.get("input_tokens", 0) * pin
        + usage.get("cache_creation_input_tokens", 0) * pin * 1.25
        + usage.get("cache_read_input_tokens", 0) * pin * 0.1
        + usage.get("output_tokens", 0) * pout
    ) / 1e6


def cost_of(doc: dict, model: str, recheck_model: str | None) -> float:
    run = doc.get("run", {})
    total = usd(run.get("judge_usage") or {}, model)
    agent = run.get("agent") or {}
    total += usd(agent.get("total_usage") or {}, model)
    if agent.get("recheck_total_usage"):
        total += usd(agent["recheck_total_usage"], recheck_model or model)
    return total


def flags(method: str, model: str, recheck_model: str | None) -> list[str]:
    spec = f"anthropic:{model}"
    if method == "M1":
        return ["--judge", "none"]
    if method == "M2":
        return ["--judge", spec]
    if method == "M3":
        return ["--agent", spec, "--agent-mode", "independent"]
    if method == "M4":
        extra = ["--agent-recheck", f"anthropic:{recheck_model}"] if recheck_model else []
        return ["--agent", spec, "--agent-mode", "combined", *extra]
    raise SystemExit(f"모르는 방식: {method}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--queue", type=Path, required=True)
    ap.add_argument("--repos", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", required=True, help="판정기 전체 모델 id(M2~M4 공통)")
    ap.add_argument("--recheck-model", default=None)
    ap.add_argument("--methods", default="M1,M2,M3,M4")
    ap.add_argument("--max-usd", type=float, required=True)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    methods = a.methods.split(",")
    if any(m != "M1" for m in methods) and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY 가 없다")
    queue = json.loads(a.queue.read_text(encoding="utf-8"))["queue"][: a.limit]
    a.out.mkdir(parents=True, exist_ok=True)
    log = a.out / "LOG.tsv"
    spent = 0.0
    done_repos = []
    for item in queue:
        folder = item["repo"].replace("/", "__", 1)
        complete = True
        for m in methods:
            dest = a.out / m / f"{folder}.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                spent += cost_of(json.loads(dest.read_text(encoding="utf-8")), a.model, a.recheck_model)
                continue
            if spent >= a.max_usd:
                complete = False
                break
            t0 = time.time()
            cmd = [
                str(BIN),
                "scan",
                str(a.repos / folder),
                *flags(m, a.model, a.recheck_model),
                "--output-format",
                "json",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            (a.out / m / f"{folder}.err").write_text(proc.stderr, encoding="utf-8")
            if proc.returncode in (0, 1):
                dest.write_text(proc.stdout, encoding="utf-8")
                cost = cost_of(json.loads(proc.stdout), a.model, a.recheck_model)
            else:
                complete, cost = False, 0.0
            spent += cost
            with open(log, "a", encoding="utf-8") as f:
                f.write(
                    f"{item['order']}\t{folder}\t{m}\t{proc.returncode}\t{time.time() - t0:.0f}"
                    f"\t{cost:.4f}\t{spent:.4f}\n"
                )
            print(f"[{item['order']:3}] {m} {folder} rc={proc.returncode} ${cost:.3f} (누계 ${spent:.2f})", flush=True)
        if not complete:
            break
        done_repos.append(item["repo"])
    (a.out / "prefix.json").write_text(
        json.dumps(
            {"complete": done_repos, "methods": methods, "usd_estimate": round(spent, 2)}, ensure_ascii=False, indent=1
        ),
        encoding="utf-8",
    )
    print(f"끝. 네 방식을 모두 마친 저장소 {len(done_repos)}곳 · 어림 ${spent:.2f} (상한 ${a.max_usd})")


if __name__ == "__main__":
    main()
