#!/usr/bin/env python3
"""두 라벨러의 답을 합친다. 갈린 단위는 조정 대상으로 내보내고, 조정 답이 오면 그것으로 정한다.

    adjudicate.py merge --a A/labels.jsonl --b B/labels.jsonl --out labels.json --disputes disputes.json
    adjudicate.py merge --a … --b … --adj ADJ/labels.jsonl --out labels.json   # 조정 뒤

  labels.json    채점 스크립트(compare.py·score.py)가 읽는 꼴. [{file, policy, label, source, scope, how}]
                 how = agreed(두 라벨러가 같음) | adjudicated(조정) | single(한쪽만 답함) | pending(갈렸고 조정 전)
  disputes.json  label.py 의 --units 로 줄 단위 목록. 두 라벨러의 답(값·이유·인용)을 함께 싣는다(label.py --disputes)

같다/다르다는 값(검토 필요·충족 근거 있음·해당 없음·가를 수 없음)으로 본다. 범위 표시가 갈리면 A 의 것을 쓰고 센다.
일치도: 네 값 카파와 '검토 필요인가' 두 값 카파를 낸다(Cohen).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def read(path: Path) -> dict[tuple[str, str], dict]:
    rows: dict[tuple[str, str], dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("label") and not r.get("error"):
                rows[(r["file"], r["policy"])] = r  # 뒤에 다시 돈 답이 앞의 답을 덮는다
    return rows


def kappa(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    n = len(pairs)
    po = sum(1 for x, y in pairs if x == y) / n
    ca, cb = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge")
    m.add_argument("--a", type=Path, required=True)
    m.add_argument("--b", type=Path, required=True)
    m.add_argument("--adj", type=Path)
    m.add_argument("--units", type=Path, help="라벨할 단위 목록(source 를 가져온다)")
    m.add_argument("--out", type=Path, required=True)
    m.add_argument("--disputes", type=Path)
    a = ap.parse_args()

    A, B = read(a.a), read(a.b)
    ADJ = read(a.adj) if a.adj else {}
    source = {}
    if a.units:
        source = {(u["file"], u["policy"]): u.get("source") for u in json.loads(a.units.read_text(encoding="utf-8"))}
    out, disputes, scope_split = [], [], 0
    for key in sorted(set(A) | set(B)):
        ra, rb = A.get(key), B.get(key)
        base = ra or rb
        row = {
            "file": key[0],
            "policy": key[1],
            "source": source.get(key, base.get("source")),
            "scope": base.get("scope"),
        }
        if ra and rb and ra["scope"] != rb["scope"]:
            scope_split += 1
        if ra and rb and ra["label"] == rb["label"]:
            out.append({**row, "label": ra["label"], "how": "agreed"})
        elif ra and rb:
            if key in ADJ:
                out.append({**row, "label": ADJ[key]["label"], "how": "adjudicated"})
            else:
                out.append({**row, "label": "unsure", "how": "pending"})
                disputes.append(
                    {
                        "file": key[0],
                        "policy": key[1],
                        "source": row["source"],
                        "answers": [
                            {k: r.get(k) for k in ("labeler", "label_ko", "reason", "citations", "scope")}
                            for r in (ra, rb)
                        ],
                    }
                )
        else:
            out.append({**row, "label": base["label"], "how": "single"})
    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.disputes:
        a.disputes.write_text(json.dumps(disputes, ensure_ascii=False, indent=1), encoding="utf-8")
    both = [(A[k]["label"], B[k]["label"]) for k in set(A) & set(B)]
    k4 = kappa(both)
    k2 = kappa([(x == "needs-review", y == "needs-review") for x, y in both])
    hows = Counter(r["how"] for r in out)
    fmt = lambda v: "n/a" if v is None else f"{v:.2f}"  # noqa: E731
    print(f"단위 {len(out)} · {dict(hows)} · 범위 표시가 갈림 {scope_split}")
    print(f"두 라벨러 일치: 네 값 카파 {fmt(k4)} · 검토 필요 여부 카파 {fmt(k2)} (둘 다 답한 {len(both)}단위)")


if __name__ == "__main__":
    main()
