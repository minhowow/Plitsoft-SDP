#!/usr/bin/env python3
"""주 지표: (저장소, 정책) 쌍 단위 F1 을 방식마다 내고, 두 방식의 차이를 저장소 부트스트랩으로 잰다.

    compare.py --labels LABELS.json --run M1=DIR --run M2=DIR --run M3=DIR --run M4=DIR \
               [--scope TAG=MODE ...] [--base M1] [--seed 20261207] [--json OUT]

입력
  LABELS.json  score.py 와 같다. [{file, policy, label, source, scope?}], file = "<저장소>/<경로>"
  DIR          방식마다 저장소당 결과 하나(<저장소>.json). 모든 방식이 policypack 의 JSON 출력과 같은 꼴이다:
               {"findings": [{"file", "policy", "outcome", ...}]}
               결과 파일이 없는 저장소는 그 방식이 실행에 실패한 것이다. 경고 없음으로 세고 따로 적는다.

세는 법 (분석 계획 4절)
  쌍의 정답    라벨이 붙은 단위 가운데 '검토 필요'가 하나라도 있으면 양성, 라벨이 있는데 하나도 없으면 음성.
               라벨이 하나도 없는 쌍(어느 방식도 경고하지 않았고 선별에도 걸리지 않은 쌍)은 정답이 없다.
  예측         그 방식이 그 저장소·정책에 경고(검토 필요·모름)를 하나라도 냈다.
  정밀도       경고한 쌍 가운데 정답이 양성인 쌍 / 경고한 쌍 가운데 정답이 있는 쌍.
  재현율       도구와 무관하게 뽑은 단위(source != flagged)로 양성이 된 쌍 가운데 경고한 쌍.
               도구가 경고해서 라벨에 더한 단위로만 양성이 된 쌍은 분모에 넣지 않는다.
  F1           위 둘의 조화 평균.
  차이의 구간  저장소를 다시 뽑아(2,000회) 두 방식의 F1 차이를 매번 계산한 백분위 95% 구간.
               방식들이 같은 저장소 표본에서 나왔으므로 짝지은 비교다.
범위 표시(--scope)는 score.py 와 같은 뜻이다(na · keep · drop).
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import random
from pathlib import Path

POS = "needs-review"


def repo_of(file: str) -> str:
    return file.split("/", 1)[0]


def load_run(folder: str) -> tuple[set[tuple[str, str]], set[str]]:
    warned, ran = set(), set()
    for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
        repo = os.path.basename(path)[:-5]
        ran.add(repo)
        for f in json.loads(Path(path).read_text(encoding="utf-8"))["findings"]:
            warned.add((repo, f["policy"]))
    return warned, ran


def truth(labels: list[dict]) -> tuple[dict, set]:
    """쌍 → 양성 여부, 그리고 도구와 무관한 단위로 양성이 된 쌍."""
    value: dict[tuple[str, str], bool] = {}
    independent = set()
    for u in labels:
        if u["label"] == "unsure":
            continue
        pair = (repo_of(u["file"]), u["policy"])
        pos = u["label"] == POS
        value[pair] = value.get(pair, False) or pos
        if pos and u.get("source") != "flagged":
            independent.add(pair)
    return value, independent


def counts(warned: set, value: dict, independent: set, repos: set) -> dict:
    w = {p for p in warned if p[0] in repos and p in value}
    tp = sum(1 for p in w if value[p])
    found = sum(1 for p in independent if p[0] in repos and p in warned)
    need = sum(1 for p in independent if p[0] in repos)
    return {"warned": len(w), "tp": tp, "found": found, "positives": need}


def f1(c: dict) -> tuple[float | None, float | None, float | None]:
    p = c["tp"] / c["warned"] if c["warned"] else None
    r = c["found"] / c["positives"] if c["positives"] else None
    if p is None or r is None:
        return p, r, None
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def pct(vals: list[float]) -> tuple[float, float] | None:
    if not vals:
        return None
    vals = sorted(vals)
    return vals[int(0.025 * len(vals))], vals[max(0, int(0.975 * len(vals)) - 1)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--labels", required=True)
    ap.add_argument("--run", action="append", required=True, metavar="METHOD=DIR")
    ap.add_argument("--scope", action="append", default=[], metavar="TAG=MODE")
    ap.add_argument("--base", default="M1")
    ap.add_argument("--seed", type=int, default=20261207)
    ap.add_argument("--rounds", type=int, default=2000)
    ap.add_argument("--json")
    a = ap.parse_args()

    modes = dict(s.split("=", 1) for s in a.scope)
    assert set(modes.values()) <= {"na", "keep", "drop"}, modes
    labels = []
    for u in json.loads(Path(a.labels).read_text(encoding="utf-8")):
        mode = modes.get(u.get("scope") or "", "keep")
        if mode != "drop":
            labels.append({**u, "label": "not-applicable"} if mode == "na" else u)
    value, independent = truth(labels)
    repos = {repo_of(u["file"]) for u in labels}
    runs = {}
    for spec in a.run:
        name, folder = spec.split("=", 1)
        runs[name] = load_run(folder)

    print(
        f"저장소 {len(repos)} · 정답이 있는 쌍 {len(value)} · 양성 쌍 {sum(value.values())} "
        f"(도구와 무관한 단위로 양성 {len(independent)})" + (f" · 범위 {modes}" if modes else "")
    )
    result = {"repos": len(repos), "scope": modes, "methods": {}, "diff": {}}
    for name, (warned, ran) in runs.items():
        c = counts(warned, value, independent, repos)
        p, r, f = f1(c)
        missing = sorted(repos - ran)
        fmt = lambda x: "  n/a" if x is None else f"{x:5.2f}"  # noqa: E731
        print(
            f"{name:4} 경고 쌍 {c['warned']:3} 정탐 {c['tp']:3} | 정밀도 {fmt(p)} 재현율 {fmt(r)} "
            f"({c['found']}/{c['positives']}) F1 {fmt(f)}" + (f" | 결과 없음 {len(missing)}곳" if missing else "")
        )
        result["methods"][name] = {**c, "precision": p, "recall": r, "f1": f, "missing": missing}

    rng = random.Random(a.seed)
    order = sorted(repos)
    boot: dict[str, list[float]] = collections.defaultdict(list)
    for _ in range(a.rounds):
        sample = collections.Counter(rng.choice(order) for _ in order)

        def score(warned, sample=sample):
            c = {"warned": 0, "tp": 0, "found": 0, "positives": 0}
            for repo, k in sample.items():
                one = counts(warned, value, independent, {repo})
                for key in c:
                    c[key] += k * one[key]
            return f1(c)[2]

        base = score(runs[a.base][0])
        for name, (warned, _) in runs.items():
            if name == a.base:
                continue
            other = score(warned)
            if base is not None and other is not None:
                boot[name].append(other - base)
    for name, vals in boot.items():
        lo_hi = pct(vals)
        mine, theirs = result["methods"][name]["f1"], result["methods"][a.base]["f1"]
        point = None if mine is None or theirs is None else mine - theirs
        text = "계산 불가" if lo_hi is None or point is None else f"{point:+.2f} (95% {lo_hi[0]:+.2f}~{lo_hi[1]:+.2f})"
        print(f"F1 차이 {name} − {a.base}: {text}  [부트스트랩 {len(vals)}/{a.rounds}회 유효]")
        result["diff"][f"{name}-{a.base}"] = {"point": point, "ci95": lo_hi, "valid_rounds": len(vals)}
    if a.json:
        Path(a.json).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
