#!/usr/bin/env python3
"""의무 지도에서 기능–의무 표를 만들고, 의무마다 적힌 조문 인용이 받아 둔 법령 원문에 글자 그대로 있는지 대조한다.
모델을 부르지 않는다.

    uv run python scripts/lawmap_table.py ~/.cache/policypack-eval/lawmap-2026-10-14

입력  <지도 폴더>/merged.json(의무 지도), <지도 폴더>/raw/(법제처 DRF 로 받은 법령·행정규칙 원문 JSON·별표 글)
      src/policypack/profile/features.yaml(기능과 의무를 붙이는 규칙)
출력  src/policypack/profile/duties.jsonl   코드에 흔적이 남는 의무(code_trace 가 no 가 아닌 것)마다 한 줄.
                                            기능·대조 결과·검토 층 후보를 싣는다
      lawmap/review-candidates.csv          검토 층 후보를 기능 묶음별로 나눈 팀원용 작업 표

대조
  원문은 그 법령 id 의 원문 파일 전부(현행·시행 예정판·별표 글)에서 조문 글만 모은다. 항·호 번호 칸(…번호)은 내용 칸과
  겹치므로 뺀다. 인용과 원문의 공백·줄바꿈은 무시하고 견준다. 인용에 생략 부호(…)가 있으면 나뉜 조각이 모두 원문에
  순서대로 있어야 한다(가장 긴 조각이 10자 이상). 원문에 섞인 개정 표시(<개정 2023. 3. 14.> 등)는 있는 채와 뺀 채
  둘 다로 견준다. 인용이 그 표시를 옮겨 적었을 수도, 뺐을 수도 있어서다.
  pass      위 방법으로 원문에 있다(how: exact 그대로 · whitespace 공백만 다름 · fragments 생략 부호로 나눈 조각)
  mismatch  원문 파일은 있는데 인용이 없다(별표 표처럼 칸이 나뉜 원문, 고쳐 적은 인용 등)
  no-source 그 법령 id 의 원문 파일이 없다

검토 층 후보 = 대조 pass · confidence high · scope general 또는 domain · 기능이 있다('지위'가 아니다).
검토 층 후보와 내장 팩(kr-core)이 다루는 의무에는 질문에 넣을 글(걸리는 신호·위반 모양·지킨 모양·주체)을 함께 싣는다.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from ruamel.yaml import YAML

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "policies" / "kr-core" / "pack.yaml"
FEATURES = REPO / "src" / "policypack" / "profile" / "features.yaml"
TABLE = REPO / "src" / "policypack" / "profile" / "duties.jsonl"
CSV_OUT = REPO / "lawmap" / "review-candidates.csv"

COMMON, STATUS = "common", "status"
_WS = re.compile(r"\s+")
_EDIT = re.compile(
    r"<(?:개정|신설|삭제|타법개정|제목개정|단서신설)[^<>]*>"
    r"|\[(?:본조신설|전문개정|제목개정|본조제목개정|종전)[^\[\]]*\]"
)
_ELLIPSIS = re.compile(r"…|\.\.\.|⋯")


def _leaves(o, key=""):
    if isinstance(o, str):
        if not key.endswith("번호"):
            yield o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from _leaves(v, k)
    elif isinstance(o, list):
        for v in o:
            yield from _leaves(v, key)


def _source(raw: Path, law_id: str, cache: dict) -> str | None:
    if law_id not in cache:
        parts = []
        for f in sorted(raw.iterdir()):
            if f.name.startswith((f"law-{law_id}", f"admrul-{law_id}")):
                text = f.read_text(encoding="utf-8", errors="replace")
                parts.extend(_leaves(json.loads(text)) if f.suffix == ".json" else [text])
        cache[law_id] = "\n".join(parts) if parts else None
    return cache[law_id]


def _squash(s: str) -> str:
    return _WS.sub("", s)


def check_quote(quote: str, source: str | None) -> tuple[str, str | None]:
    if source is None:
        return "no-source", None
    q = _squash(quote)
    pieces = [_squash(p) for p in _ELLIPSIS.split(quote) if _squash(p)]
    for text in (source, _EDIT.sub("", source)):
        flat = _squash(text)
        if quote and quote in text:
            return "pass", "exact"
        if q and q in flat:
            return "pass", "whitespace"
        if _ELLIPSIS.search(quote) and pieces and max(map(len, pieces)) >= 10:
            pos = 0
            for p in pieces:
                pos = flat.find(p, pos)
                if pos < 0:
                    break
                pos += len(p)
            else:
                return "pass", "fragments"
    return "mismatch", None


def assign(duty: dict, by_id: dict[str, str], by_note: dict[str, str]) -> str | None:
    if duty["scope"] == "sector":
        return STATUS
    return by_id.get(duty["id"]) or by_note.get(duty["scope_note"])


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    lawmap = Path(argv[0]).expanduser()
    merged = json.loads((lawmap / "merged.json").read_text(encoding="utf-8"))
    duties = [d for cluster in merged.values() for d in cluster["duties"] if d["code_trace"] != "no"]

    spec = YAML(typ="safe").load(FEATURES.read_text(encoding="utf-8"))
    groups = [{"id": COMMON, **spec["common"]}, *spec["features"]]
    by_id, by_note = {}, {}
    for g in groups:
        for i in g.get("duties") or []:
            assert i not in by_id, f"의무 {i} 가 두 기능에 붙었습니다"
            by_id[i] = g["id"]
        for n in g.get("scope_notes") or []:
            assert n not in by_note, f"scope_note {n} 가 두 기능에 붙었습니다"
            by_note[n] = g["id"]
    known = {d["id"] for d in duties}
    stray = sorted(set(by_id) - known)
    assert not stray, f"의무 지도에 없는 id: {stray}"

    from policypack.pack.loader import load_pack

    krcore = {d for p in load_pack(PACK).policies for d in p.duties}
    raw, cache, rows, unmapped = lawmap / "raw", {}, [], []
    for d in duties:
        feature = assign(d, by_id, by_note)
        if feature is None:
            unmapped.append(d)
            continue
        if d["scope"] == "sector" and d["id"] in by_id:
            print(f"알림: {d['id']} 는 scope sector 라 '지위'로 둡니다(features.yaml 의 {by_id[d['id']]} 대신)")
        check, how = check_quote(d["quote"], _source(raw, d["law_id"], cache))
        candidate = (
            check == "pass" and d["confidence"] == "high" and d["scope"] in ("general", "domain") and feature != STATUS
        )
        asked = candidate or d["id"] in krcore
        rows.append(
            {
                "id": d["id"],
                "feature": feature,
                "law": d["law"],
                "law_short": d["law_short"],
                "kind": d["kind"],
                "article": d["article"],
                "title": d["title"],
                "duty": d["duty_ko"],
                "url": d["source_url"],
                "scope": d["scope"],
                "scope_note": d["scope_note"],
                "confidence": d["confidence"],
                "detect": d["detect"],
                "quote": d["quote"],
                "quote_check": check,
                "quote_how": how,
                "review_candidate": candidate,
                "krcore": d["id"] in krcore,
                **(
                    {
                        "addressee": d["addressee"],
                        "trigger": d["trigger_ko"],
                        "violation_shapes": d["violation_shapes_ko"],
                        "compliant_shapes": d["compliant_shapes_ko"],
                    }
                    if asked
                    else {}
                ),
            }
        )
    if unmapped:
        for d in unmapped:
            print(f"기능이 없는 의무: {d['id']} ({d['scope']} / {d['scope_note']}) {d['title']}", file=sys.stderr)
        return 1

    order = {g["id"]: i for i, g in enumerate(groups)} | {STATUS: len(groups)}
    rows.sort(key=lambda r: (order[r["feature"]], r["id"]))
    TABLE.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    names = {g["id"]: g["name"] for g in groups} | {STATUS: spec["status"]["name"]}
    CSV_OUT.parent.mkdir(exist_ok=True)
    with CSV_OUT.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["기능", "id", "법", "조문", "의무 한 줄", "인용", "링크", "대조 결과", "확인할 것"])
        for r in rows:
            if r["review_candidate"]:
                w.writerow(
                    [names[r["feature"]], r["id"], r["law"], r["article"], r["duty"], r["quote"], r["url"],
                     f"통과({r['quote_how']})", ""]
                )  # fmt: skip

    checks = Counter(r["quote_check"] for r in rows)
    hows = Counter(r["quote_how"] for r in rows if r["quote_how"])
    print(f"의무 {len(rows)}개 → {TABLE.relative_to(REPO)}")
    print(f"조문 인용 대조: 통과 {checks['pass']} ({dict(hows)})", end=" · ")
    print(f"불일치 {checks['mismatch']} · 원문 없음 {checks['no-source']}")
    per = defaultdict(lambda: [0, 0])
    for r in rows:
        per[r["feature"]][0] += 1
        per[r["feature"]][1] += r["review_candidate"]
    total = sum(v[1] for v in per.values())
    print(f"검토 층 후보 {total}개 → {CSV_OUT.relative_to(REPO)}")
    print("| 기능 | 의무 | 검토 층 후보 |\n|---|---|---|")
    for g in sorted(per, key=order.get):
        print(f"| {names[g]} | {per[g][0]} | {per[g][1]} |")
    for r in rows:
        if r["quote_check"] != "pass":
            print(f"  {r['quote_check']}: {r['id']} {r['law_short']} {r['article']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
