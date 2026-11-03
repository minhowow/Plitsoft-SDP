#!/usr/bin/env python3
"""사람이 블라인드로 볼 감사 표본을 만든다. 네트워크를 쓰지 않는다.

    audit_sample.py --labels LABELS.json --scans M1=DIR --scans M2=DIR ... --random HEX \
                    --out-blind blind.json --out-key key.json

  경고는 네 방식(M1~M4) 가운데 하나라도 낸 (파일, 정책)의 합집합이다. 어느 방식이 냈는지는 key.json 에만 둔다.
  경고(최대 60건, 넘으면 정책별 층화 무작위) + 경고가 아닌 단위 60건:
    LLM 라벨이 '검토 필요'인 것 30건(포착하지 못한 (저장소, 정책) 쌍마다 1건씩 먼저) + 그 밖 30건(정책을 경고와 맞춤).
  blind.json 에는 파일과 정책만 있다. 순서는 섞는다. 도구 출력, LLM 라벨, 뽑힌 까닭은 key.json 에만 둔다.
  사람은 blind.json 만 본다. key.json 은 사람 라벨의 해시를 남긴 뒤에 연다.
"""

from __future__ import annotations

import argparse
import collections
import glob
import hashlib
import json
import os
from pathlib import Path

POS = "needs-review"
MAX_WARN, N_POS, N_NEG = 60, 30, 30


def order(items: list, rnd: str, salt: str) -> list:
    return sorted(items, key=lambda k: hashlib.sha256(f"{rnd}:{salt}:{k[0]}:{k[1]}".encode()).hexdigest())


def stratified(items: list, n: int, rnd: str, salt: str) -> list:
    """정책마다 돌아가며 하나씩 뽑는다. 정책 하나가 표본을 다 차지하지 못하게 한다."""
    by = collections.defaultdict(list)
    for k in order(items, rnd, salt):
        by[k[1]].append(k)
    out = []
    while len(out) < n and any(by.values()):
        for pol in sorted(by):
            if by[pol] and len(out) < n:
                out.append(by[pol].pop(0))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--labels", required=True)
    ap.add_argument("--scans", action="append", required=True, metavar="METHOD=DIR")
    ap.add_argument("--random", required=True)
    ap.add_argument("--out-blind", required=True)
    ap.add_argument("--out-key", required=True)
    a = ap.parse_args()
    rnd = a.random.strip().lower()

    labels = {(u["file"], u["policy"]): u for u in json.loads(Path(a.labels).read_text(encoding="utf-8"))}
    by_method = collections.defaultdict(set)
    for spec in a.scans:
        method, folder = spec.split("=", 1)
        for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
            repo = os.path.basename(path)[:-5]
            for f in json.loads(Path(path).read_text(encoding="utf-8"))["findings"]:
                by_method[(f"{repo}/{f['file']}", f["policy"])].add(method)
    warned = set(by_method)

    warn = stratified(sorted(warned), MAX_WARN, rnd, "warn")

    def pair(k):
        return (k[0].split("/", 1)[0], k[1])

    independent = {k: u for k, u in labels.items() if u.get("source") != "flagged" and k not in warned}
    caught = {pair(k) for k in warned if labels.get(k, {}).get("label") == POS}
    missed_pos = [k for k, u in independent.items() if u["label"] == POS]
    first, seen_pairs = [], set()
    for k in order(missed_pos, rnd, "pos"):
        if pair(k) not in caught and pair(k) not in seen_pairs:
            first.append(k)
            seen_pairs.add(pair(k))
    rest = [k for k in order(missed_pos, rnd, "pos") if k not in first]
    pos = (first + rest)[:N_POS]

    want = collections.Counter(k[1] for k in warn)
    negs = [k for k, u in independent.items() if u["label"] != POS]
    neg = []
    for pol, _ in want.most_common():
        share = round(N_NEG * want[pol] / max(1, len(warn)))
        neg += [k for k in order(negs, rnd, "neg") if k[1] == pol][:share]
    neg += [k for k in order(negs, rnd, "neg") if k not in neg][: max(0, N_NEG - len(neg))]
    neg = neg[:N_NEG]

    parts = (("warning", warn), ("llm-positive", pos), ("llm-other", neg))
    key = [
        {"file": f, "policy": p, "why": why, "methods": sorted(by_method.get((f, p), ()))}
        for why, part in parts
        for f, p in part
    ]
    blind = [
        {"file": k["file"], "policy": k["policy"]}
        for k in sorted(key, key=lambda k: hashlib.sha256(f"{rnd}:mix:{k['file']}:{k['policy']}".encode()).hexdigest())
    ]
    Path(a.out_blind).write_text(json.dumps(blind, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(a.out_key).write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"경고 {len(warn)}/{len(warned)} · LLM 양성 {len(pos)}(쌍 우선 {len(first)})"
        f" · 그 밖 {len(neg)} · 합계 {len(blind)}"
    )


if __name__ == "__main__":
    main()
