#!/usr/bin/env python3
"""부 지표: (시작 파일, 정책) 단위 채점. 방식마다 한 번씩 돌린다. 주 지표(쌍 단위 F1)는 compare.py 가 낸다.

    score.py --labels LABELS.json --scans DIR [--audit AUDIT.json] [--scope TAG=MODE ...] [--seed N] [--json OUT]

입력
  LABELS.json  [{file, policy, label, source}, ...]
               file   = "<저장소>/<저장소 안 경로>"
               label  = needs-review | compliant | not-applicable | unsure
               source = 도구와 무관하게 뽑은 단위면 screened·unscreened, 도구가 경고해서 더한 단위면 flagged
               scope  = (선택) 범위가 갈리는 단위의 표시(guide/LABEL_GUIDE.md 의 이름)
  DIR          저장소마다 한 방식의 결과 하나(<저장소>.json, policypack scan --output-format json 꼴)
  AUDIT.json   (선택) 사람이 블라인드로 본 단위 [{file, policy, human}]

범위 표시를 다루는 법 (--scope TAG=MODE, PROTOCOL.md 4절의 표)
  na    그 표시가 붙은 단위의 정답을 '해당 없음'으로 본다(판단 대상 없음). 거기 난 경고는 오경보다
  keep  라벨러가 적은 값을 그대로 쓴다
  drop  그 단위를 아예 뺀다
  적지 않은 표시는 keep 이다. 주 칸은 PROTOCOL.md 4절이 정한다.

세는 법
  경고 = findings 의 (파일, 정책). 한 정책의 규칙 여럿이 걸려도 한 번 센다.
  정밀도 = 정답이 needs-review 인 경고 / 정답이 있는 경고. unsure 는 뺀다.
  포착률(재현율) = 도구와 무관하게 뽑은 단위(source != flagged) 가운데 정답이 needs-review 인 것 중 경고가 난 비율.
           도구가 경고해서 라벨 대상에 더한 단위를 분모에 넣으면 값이 부풀려진다(9/30 dev 0.52 의 원인).
  엔진 미완 경고(untested_reasons 에 engine-incomplete)는 따로도 센다. 기계 부하에 따라 달라진다.
  구간 = Wilson 95%, 그리고 저장소를 다시 뽑는 부트스트랩 95%(양성이 저장소 몇 곳에 몰리는 것을 반영).
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import math
import os
import random
from pathlib import Path

POS = "needs-review"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def load_scans(folder: str) -> dict[tuple[str, str], dict]:
    """(파일, 정책) → {outcome 들, 엔진 미완 여부}."""
    out: dict[tuple[str, str], dict] = {}
    for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
        repo = os.path.basename(path)[:-5]
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        for f in doc["findings"]:
            key = (f"{repo}/{f['file']}", f["policy"])
            rec = out.setdefault(key, {"outcomes": set(), "only_incomplete": True})
            rec["outcomes"].add(f["outcome"])
            if "engine-incomplete" not in f.get("untested_reasons", []):
                rec["only_incomplete"] = False
    return out


def repo_of(file: str) -> str:
    return file.split("/", 1)[0]


def tally(units: list[dict], flagged: dict, truth: str) -> collections.Counter:
    """units: 정답이 있는 단위들. truth: 정답 칸 이름."""
    c: collections.Counter = collections.Counter()
    for u in units:
        t = u[truth]
        if t == "unsure":
            c["unsure"] += 1
            continue
        hit = (u["file"], u["policy"]) in flagged
        pos = t == POS
        c[("tp" if hit else "fn") if pos else ("fp" if hit else "tn")] += 1
    return c


def ratio(k: int, n: int) -> str:
    if n == 0:
        return "  n/a (0건)"
    lo, hi = wilson(k, n)
    return f"{k / n:.2f} ({k}/{n}; Wilson {lo:.2f}–{hi:.2f})"


def bootstrap(units: list[dict], flagged: dict, truth: str, stat, seed: int, rounds: int = 2000) -> str:
    repos = sorted({repo_of(u["file"]) for u in units})
    if len(repos) < 2:
        return "저장소 1곳"
    by = collections.defaultdict(list)
    for u in units:
        by[repo_of(u["file"])].append(u)
    rng, vals = random.Random(seed), []
    for _ in range(rounds):
        sample = [u for r in (rng.choice(repos) for _ in repos) for u in by[r]]
        v = stat(tally(sample, flagged, truth))
        if v is not None:
            vals.append(v)
    if not vals:
        return "계산 불가"
    vals.sort()
    return f"저장소 부트스트랩 {vals[int(0.025 * len(vals))]:.2f}–{vals[int(0.975 * len(vals)) - 1]:.2f}"


def precision(c):
    n = c["tp"] + c["fp"]
    return c["tp"] / n if n else None


def recall(c):
    n = c["tp"] + c["fn"]
    return c["tp"] / n if n else None


def report(title: str, units: list[dict], flagged: dict, truth: str, seed: int, want: str) -> dict:
    out = {}
    policies = sorted({u["policy"] for u in units})
    print(f"\n## {title}  (단위 {len(units)}개)")
    for pol in [*policies, "전체"]:
        part = units if pol == "전체" else [u for u in units if u["policy"] == pol]
        c = tally(part, flagged, truth)
        line = f"{pol:24} tp={c['tp']:3} fp={c['fp']:3} fn={c['fn']:3} tn={c['tn']:4} unsure={c['unsure']:2}"
        if want in ("precision", "both"):
            line += f" | 정밀도 {ratio(c['tp'], c['tp'] + c['fp'])}"
        if want in ("recall", "both"):
            line += f" | 포착률 {ratio(c['tp'], c['tp'] + c['fn'])}"
        if pol == "전체":
            stat = precision if want == "precision" else recall
            line += f" | {bootstrap(part, flagged, truth, stat, seed)}"
            positives = collections.Counter(repo_of(u["file"]) for u in part if u[truth] == POS)
            if positives:
                top = positives.most_common(2)
                line += f" | 양성 {sum(positives.values())}건 중 {sum(n for _, n in top)}건이 저장소 {len(top)}곳"
        print(line)
        out[pol] = dict(c)
    return out


def pairs(independent: list[dict], flagged: dict) -> dict:
    """(저장소, 정책) 쌍 포착률. 분모: 도구와 무관하게 뽑은 단위 가운데 '검토 필요'가 하나라도 있는 쌍.
    포착: 그 쌍의 '검토 필요' 단위에 경고가 하나라도 났다. 느슨한 값: 그 저장소에서 그 정책의 경고가 하나라도 났다."""
    positive = collections.defaultdict(list)
    for u in independent:
        if u["label"] == POS:
            positive[(repo_of(u["file"]), u["policy"])].append(u["file"])
    warned_pairs = {(repo_of(f), p) for f, p in flagged}
    out = {}
    print(f"\n## 쌍 포착률 — (저장소, 정책) 쌍 {len(positive)}개")
    for pol in [*sorted({p for _, p in positive}), "전체"]:
        mine = {k: v for k, v in positive.items() if pol == "전체" or k[1] == pol}
        strict = sum(1 for (r, p), files in mine.items() if any((f, p) in flagged for f in files))
        loose = sum(1 for k in mine if k in warned_pairs)
        print(
            f"{pol:24} 쌍 {len(mine):3} | 포착 {ratio(strict, len(mine))}"
            f" | 느슨하게(그 저장소·정책에 경고가 있음) {loose}/{len(mine)}"
        )
        out[pol] = {"pairs": len(mine), "captured": strict, "loose": loose}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--labels", required=True)
    ap.add_argument("--scans", required=True)
    ap.add_argument("--audit")
    ap.add_argument("--scope", action="append", default=[], metavar="TAG=MODE")
    ap.add_argument("--seed", type=int, default=20261120)
    ap.add_argument("--json")
    a = ap.parse_args()

    modes = dict(s.split("=", 1) for s in a.scope)
    assert set(modes.values()) <= {"na", "keep", "drop"}, modes

    def scoped(units: list[dict], truth: str) -> list[dict]:
        out = []
        for u in units:
            mode = modes.get(u.get("scope") or "", "keep")
            if mode == "drop":
                continue
            out.append({**u, truth: "not-applicable"} if mode == "na" else u)
        return out

    labels = scoped(json.loads(Path(a.labels).read_text(encoding="utf-8")), "label")
    if modes:
        print("범위 표시:", modes)
    flagged_all = load_scans(a.scans)
    solid = {k: v for k, v in flagged_all.items() if not v["only_incomplete"]}
    print(f"경고 (파일, 정책) {len(flagged_all)}개 · 그중 엔진 미완에서만 나온 것 {len(flagged_all) - len(solid)}개")

    result = {}
    result["정밀도: LLM 라벨이 있는 경고"] = report(
        "정밀도 — 라벨이 있는 모든 단위", labels, flagged_all, "label", a.seed, "precision"
    )
    independent = [u for u in labels if u.get("source") != "flagged"]
    result["포착률: 도구와 무관하게 뽑은 단위"] = report(
        "포착률 — 도구와 무관하게 뽑은 단위만", independent, flagged_all, "label", a.seed, "recall"
    )
    result["쌍 포착률"] = pairs(independent, flagged_all)
    if len(solid) != len(flagged_all):
        result["정밀도: 엔진 미완 경고 제외"] = report(
            "정밀도 — 엔진 미완에서만 나온 경고를 뺌", labels, solid, "label", a.seed, "precision"
        )
    unlabelled = sorted(k for k in flagged_all if k not in {(u["file"], u["policy"]) for u in labels})
    print(
        f"\n라벨이 없는 경고 {len(unlabelled)}개"
        + (": " + ", ".join(f"{f} [{p}]" for f, p in unlabelled[:5]) if unlabelled else "")
    )
    if a.audit:
        audit = scoped(json.loads(Path(a.audit).read_text(encoding="utf-8")), "human")
        result["정밀도: 사람이 본 경고"] = report(
            "사람 감사 — 사람이 블라인드로 본 단위", audit, flagged_all, "human", a.seed, "both"
        )
        llm = {(u["file"], u["policy"]): u["label"] for u in labels}
        both = [(u["human"], llm[(u["file"], u["policy"])]) for u in audit if (u["file"], u["policy"]) in llm]
        agree = sum(1 for h, m in both if (h == POS) == (m == POS))
        print(f"\n사람과 LLM 라벨의 일치(검토 필요 여부): {ratio(agree, len(both))}")
    if a.json:
        Path(a.json).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
