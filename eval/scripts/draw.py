#!/usr/bin/env python3
"""후보 스냅샷에서 층별 표본을 뽑고, 처리 순서(대기열)를 정한다. 네트워크를 쓰지 않는다.

    draw.py --candidates candidates.json --hold eval/ads-holdout.json --random HEX \
            --alloc genai=14,msg=8,signup=9,shop=9 --out draw.json

순서는 SHA-256(난수 ‖ ":" ‖ 저장소 id)의 오름차순이다. 난수는 후보 스냅샷의 해시를 남긴 뒤에 정해지는 공개 값
(미리 적어 둔 drand 라운드의 출력, beacon.py)이다. 같은 입력이면 누가 돌려도 같은 표본이 나온다.
소유자 한 명에서 두 개까지만 뽑는다(층을 통틀어). 층은 --alloc 에 적은 순서대로 처리한다.
광고 보류분은 무작위 추출이 아니라 모두 쓴다. 순서만 SHA-256(난수 ‖ ":" ‖ owner/name)으로 정한다.

대기열(queue): 층마다 순번 1을 모두, 그다음 순번 2를 모두 … 의 순서로 섞는다(층 순서는 --alloc, 광고는 맨 뒤).
라벨·실행은 이 순서로 하고, 기한이나 비용 상한에 닿으면 끝까지 마친 앞부분만 쓴다(분석 계획 5절).
뽑힌 저장소를 내려받지 못하면 같은 층의 다음 순번을 그 자리에 넣는다(--failed 로 알려 준다).
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

OWNER_CAP = 2


def key(rnd: str, ident: str | int) -> str:
    return hashlib.sha256(f"{rnd}:{ident}".encode()).hexdigest()


def draw(rows: list[dict], rnd: str, alloc: dict[str, int], failed: set[str]) -> list[dict]:
    owners: collections.Counter = collections.Counter()
    out = []
    for stratum, n in alloc.items():
        taken = 0
        ranked = sorted((r for r in rows if r["stratum"] == stratum), key=lambda r: key(rnd, r["id"]))
        for rank, r in enumerate(ranked, 1):
            skipped = None
            if owners[r["owner"].lower()] >= OWNER_CAP:
                skipped = "owner-cap"
            elif r["repo"].lower() in failed:
                skipped = "clone-failed"
            picked = skipped is None and taken < n
            if picked:
                owners[r["owner"].lower()] += 1
                taken += 1
            out.append({**r, "rank": rank, "picked": picked, "slot": taken if picked else None, "skipped": skipped})
    return out


def queue(drawn: list[dict], hold: list[str], rnd: str, strata: list[str]) -> list[dict]:
    streams = {s: [r for r in drawn if r["stratum"] == s and r["picked"]] for s in strata}
    streams["ads-hold"] = [
        {"repo": name, "stratum": "ads-hold", "slot": i}
        for i, name in enumerate(sorted(hold, key=lambda n: key(rnd, n.lower())), 1)
    ]
    out = []
    for slot in range(1, max((len(v) for v in streams.values()), default=0) + 1):
        for s in [*strata, "ads-hold"]:
            if slot <= len(streams[s]):
                r = streams[s][slot - 1]
                out.append({"order": len(out) + 1, "repo": r["repo"], "stratum": s, "slot": slot})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--candidates", type=Path, required=True)
    ap.add_argument("--hold", type=Path, required=True)
    ap.add_argument("--random", required=True, help="공개 난수(16진 문자열)")
    ap.add_argument("--alloc", required=True, help="층=개수 를 쉼표로")
    ap.add_argument("--failed", default="", help="내려받지 못한 저장소 owner/name 을 쉼표로")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    rows = json.loads(a.candidates.read_text(encoding="utf-8"))
    hold = json.loads(a.hold.read_text(encoding="utf-8"))["repos"]
    alloc = {k: int(v) for k, v in (kv.split("=") for kv in a.alloc.split(","))}
    failed = {f.strip().lower() for f in a.failed.split(",") if f.strip()}
    rnd = a.random.strip().lower()
    drawn = draw(rows, rnd, alloc, failed)
    result = {"random": rnd, "alloc": alloc, "queue": queue(drawn, hold, rnd, list(alloc)), "ranked": drawn}
    a.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for s, n in alloc.items():
        have = sum(1 for r in drawn if r["stratum"] == s)
        got = sum(1 for r in drawn if r["stratum"] == s and r["picked"])
        note = "  ← 후보가 배분의 3배에 못 미친다" if have < 3 * n else ""
        print(f"{s:8} 후보 {have:4} · 뽑음 {got}/{n}{note}")
    print(f"광고 보류 {len(hold)} · 대기열 {len(result['queue'])}")


if __name__ == "__main__":
    main()
