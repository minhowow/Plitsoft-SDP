#!/usr/bin/env python3
"""후보 저장소 스냅샷을 만든다(GitHub 저장소 검색, 메타데이터만).

    candidates.py fetch  --out SNAPDIR            # 네트워크를 쓴다. 소유자 승인 뒤에만 돌린다
    candidates.py build  --raw SNAPDIR --seen eval/seen.txt --hold eval/ads-holdout.json --out candidates.json

fetch 는 질의마다 검색 API 응답을 그대로 저장한다(raw/<질의 id>-p<쪽>.json, log.tsv).
build 는 저장한 응답에서 후보 목록을 만든다. 네트워크를 쓰지 않으므로 같은 응답이면 결과가 같다.

제외는 메타데이터와 이름·설명 정규식으로만 한다. 사람이 판단해서 빼지 않는다.
  포크, 보관(archived), 템플릿 저장소, 크기 100KB 미만·60MB 초과, 주 언어가 JavaScript·TypeScript 가 아님,
  이름·설명이 SDK·템플릿·예제·튜토리얼 꼴, 이미 본 저장소(seen.txt: 한 줄에 owner/name, # 뒤는 주석),
  광고 보류분(ads-holdout.json: 무작위 추출과 따로 모두 쓴다).
층 배정: 여러 층의 질의에 걸린 저장소는 후보가 가장 적은 층에 둔다(같으면 STRATA 순서).
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

COMMON = "language:TypeScript language:JavaScript size:100..60000"
STRATA = ("genai", "msg", "signup", "shop")
#: 질의 id → (층, 질의). 서비스 종류를 가리키는 한국어 낱말로 고른다. 팩의 패턴에서 가져온 낱말이 아니다.
QUERIES = {
    "g1": ("genai", "챗봇 in:readme,description"),
    "g2": ("genai", "생성형 AI in:readme,description"),
    "g3": ("genai", "GPT 서비스 in:readme"),
    "m1": ("msg", "푸시 알림 in:readme,description"),
    "m2": ("msg", "문자 발송 in:readme,description"),
    "m3": ("msg", "알림 서비스 in:readme"),
    "s1": ("signup", "회원가입 in:readme,description"),
    "s2": ("signup", "로그인 회원가입 서비스 in:readme"),
    "h1": ("shop", "쇼핑몰 in:readme,description"),
    "h2": ("shop", "커머스 주문 결제 in:readme"),
}
PAGES = 3  # 질의마다 100개씩 최대 3쪽
NOT_A_SERVICE = re.compile(
    r"(?i)(?<![a-z])(sdk|template|boilerplate|starter|example|examples|sample|tutorial|awesome|cheatsheet)(?![a-z])"
    r"|예제|템플릿|튜토리얼|보일러플레이트|실습"
)
LANGS = {"JavaScript", "TypeScript"}


def fetch(out: Path) -> None:
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    with open(out / "log.tsv", "a", encoding="utf-8") as log:
        for qid, (_, q) in QUERIES.items():
            for page in range(1, PAGES + 1):
                url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
                    {"q": f"{q} {COMMON}", "per_page": 100, "page": page}
                )
                req = urllib.request.Request(
                    url, headers={"Accept": "application/vnd.github+json", "User-Agent": "repo-sample"}
                )
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = r.read()
                (raw / f"{qid}-p{page}.json").write_bytes(body)
                doc = json.loads(body)
                log.write(
                    f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')}\t{qid}\t{page}\t{doc.get('total_count')}"
                    f"\t{len(doc.get('items', []))}\t{q} {COMMON}\n"
                )
                log.flush()
                time.sleep(7)  # 인증 없는 검색은 분당 10회다
                if len(doc.get("items", [])) < 100:
                    break


def excluded(item: dict, seen: set[str]) -> str | None:
    """빼는 까닭. 빼지 않으면 None."""
    if item["full_name"].lower() in seen:
        return "seen"
    if item.get("fork"):
        return "fork"
    if item.get("archived") or item.get("disabled"):
        return "archived"
    if item.get("is_template"):
        return "template-repo"
    if not 100 <= item.get("size", 0) <= 60000:
        return "size"
    if item.get("language") not in LANGS:
        return "language"
    if NOT_A_SERVICE.search(f"{item['name']} {item.get('description') or ''}"):
        return "not-a-service"
    return None


def build(raw: Path, seen_file: Path | None, hold_file: Path | None, out: Path) -> None:
    seen = set()
    if seen_file:
        lines = (line.split("#", 1)[0].strip() for line in seen_file.read_text(encoding="utf-8").splitlines())
        seen = {line.lower() for line in lines if line}
    if hold_file:
        seen |= {r.lower() for r in json.loads(hold_file.read_text(encoding="utf-8"))["repos"]}
    found: dict[int, dict] = {}
    hits: dict[int, set[str]] = collections.defaultdict(set)
    for path in sorted(raw.glob("*.json")):
        qid = path.name.split("-p")[0]
        if qid not in QUERIES:
            continue
        for item in json.loads(path.read_text(encoding="utf-8")).get("items", []):
            found[item["id"]] = item
            hits[item["id"]].add(qid)
    why = collections.Counter()
    kept = {}
    for rid, item in found.items():
        reason = excluded(item, seen)
        if reason:
            why[reason] += 1
            continue
        kept[rid] = item
    per = collections.Counter(s for rid in kept for s in {QUERIES[q][0] for q in hits[rid]})
    rows = []
    for rid, item in sorted(kept.items()):
        strata = {QUERIES[q][0] for q in hits[rid]}
        stratum = min(strata, key=lambda s: (per[s], STRATA.index(s)))
        rows.append(
            {
                "id": rid,
                "repo": item["full_name"],
                "owner": item["owner"]["login"],
                "stratum": stratum,
                "queries": sorted(hits[rid]),
                "size_kb": item["size"],
                "language": item["language"],
                "stars": item["stargazers_count"],
                "pushed": item["pushed_at"][:10],
                "default_branch": item["default_branch"],
            }
        )
    text = json.dumps(rows, ensure_ascii=False, indent=1) + "\n"
    out.write_text(text, encoding="utf-8")
    print(
        f"찾은 저장소 {len(found)} · 뺀 것 {dict(why)} · 후보 {len(rows)}"
        f" · 층별 {dict(collections.Counter(r['stratum'] for r in rows))}"
    )
    print(f"sha256 {hashlib.sha256(text.encode('utf-8')).hexdigest()}  {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--out", type=Path, required=True)
    b = sub.add_parser("build")
    b.add_argument("--raw", type=Path, required=True)
    b.add_argument("--seen", type=Path)
    b.add_argument("--hold", type=Path)
    b.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.out)
    else:
        build(a.raw, a.seen, a.hold, a.out)


if __name__ == "__main__":
    sys.exit(main())
