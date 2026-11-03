#!/usr/bin/env python3
"""라벨할 (시작 파일, 정책) 단위를 뽑는다. 도구의 판정과 무관하다. 네트워크를 쓰지 않는다.

  units.py --repos DIR --screen screen.json --random HEX --out units.json

DIR         저장소마다 폴더 하나(<owner>__<name>)
screen.json {정책 id: [[낱말 묶음], [낱말 묶음], ...]} — 파일이 모든 묶음에서 낱말을 하나 이상 가지면 그 정책의
            선별 단위다. 낱말은 정규식이고 대소문자를 가리지 않는다. 라벨 기준서를 쓴 세션이 썼다(guide/).
파일        policypack 이 검사 대상으로 고르는 파일과 같다(policypack.discover).
상한        저장소·정책마다 선별 단위 4개. 넘으면 SHA-256(난수 ‖ 파일 ‖ 정책) 순서로 앞에서부터.
선별 밖     저장소마다, 어느 정책에도 선별되지 않은 파일 하나와 정책 하나를 같은 순서 규칙으로 고른다.
            선별이 놓친 '검토 필요'가 얼마나 되는지 어림하려는 표본이다.
시작 파일   라벨러는 이 파일에서 시작해 같은 저장소의 다른 파일을 읽을 수 있다(guide/labeller-prompt.md).
            그래서 단위는 파일 하나지만 정답은 저장소 전체를 보고 붙는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from policypack.discover import discover

CAP = 4
#: 내장 팩이 보는 언어(pack.yaml 의 defaults.languages)
LANGUAGES = ["javascript", "typescript"]


def rank(rnd: str, *parts: str) -> str:
    return hashlib.sha256(":".join((rnd, *parts)).encode()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repos", type=Path, required=True)
    ap.add_argument("--screen", type=Path, required=True)
    ap.add_argument("--random", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    rnd = a.random.strip().lower()
    screen = {k: v for k, v in json.loads(a.screen.read_text(encoding="utf-8")).items() if not k.startswith("_")}
    groups = {pol: [[re.compile(w, re.I) for w in g] for g in gs] for pol, gs in screen.items()}

    units, summary = [], []
    for repo in sorted(p for p in a.repos.iterdir() if p.is_dir()):
        files = sorted(discover([repo], LANGUAGES).files)
        hit: dict[str, list[str]] = {pol: [] for pol in groups}
        screened_files = set()
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = f"{repo.name}/{f.relative_to(repo).as_posix()}"
            for pol, gs in groups.items():
                if all(any(w.search(text) for w in g) for g in gs):
                    hit[pol].append(rel)
                    screened_files.add(rel)
        for pol, rels in hit.items():
            for rel in sorted(rels, key=lambda r: rank(rnd, r, pol))[:CAP]:
                units.append({"file": rel, "policy": pol, "source": "screened"})
        rest = [f"{repo.name}/{f.relative_to(repo).as_posix()}" for f in files]
        rest = sorted((r for r in rest if r not in screened_files), key=lambda r: rank(rnd, r, "unscreened"))
        if rest:
            pol = min(groups, key=lambda p: rank(rnd, rest[0], p))
            units.append({"file": rest[0], "policy": pol, "source": "unscreened"})
        summary.append((repo.name, len(files), {p.split(".")[-1]: len(v) for p, v in hit.items() if v}))

    a.out.write_text(json.dumps(units, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for name, n, hits in summary:
        print(f"{name:48} 파일 {n:5}  선별 {hits}")
    by = {}
    for u in units:
        by[u["source"]] = by.get(u["source"], 0) + 1
    print(f"단위 {len(units)}개 {by} · 저장소 {len(summary)}곳 · 저장소당 {len(units) / max(1, len(summary)):.1f}개")


if __name__ == "__main__":
    main()
