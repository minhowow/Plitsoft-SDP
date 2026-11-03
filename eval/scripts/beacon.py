#!/usr/bin/env python3
"""공개 난수를 받는다(drand mainnet, League of Entropy). 네트워크를 쓴다. 소유자 승인 뒤에만 돌린다.

    beacon.py round  2026-12-01T12:00:00+09:00     # 그 시각의 라운드 번호(네트워크를 쓰지 않는다)
    beacon.py fetch  ROUND --out beacon.json       # 두 중계에서 받아 같은지 보고 저장한다

라운드는 30초마다 하나다. 라운드 번호는 PROTOCOL.md 에 미리 적어 고정했다. 그 시각이 지나기 전에는 아무도 값을 모른다.
받은 값의 randomness 는 SHA-256(signature) 와 같아야 한다(여기서 확인한다). 서명 자체(BLS)의 검증은 하지 않고,
서로 다른 운영자의 중계 두 곳이 같은 값을 주는지로 갈음한다. 저장한 응답으로 누구든 다시 확인할 수 있다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

CHAIN = "8990e7a9aaed2ffed73dbd7092123d6f289930540d7651336225dc172e51b2ce"  # mainnet default(chained)
GENESIS, PERIOD = 1595431050, 30
RELAYS = ("https://api.drand.sh", "https://drand.cloudflare.com")


def round_at(when: str) -> int:
    t = int(dt.datetime.fromisoformat(when).timestamp())
    return (t - GENESIS) // PERIOD + 1


def fetch(rnd: int, out: Path) -> None:
    got = {}
    for relay in RELAYS:
        url = f"{relay}/{CHAIN}/public/{rnd}"
        req = urllib.request.Request(url, headers={"User-Agent": "repo-sample"})
        with urllib.request.urlopen(req, timeout=30) as r:
            got[relay] = json.loads(r.read())
    values = {g["randomness"] for g in got.values()}
    if len(values) != 1:
        sys.exit(f"중계마다 값이 다르다: {values}")
    first = next(iter(got.values()))
    if hashlib.sha256(bytes.fromhex(first["signature"])).hexdigest() != first["randomness"]:
        sys.exit("randomness 가 SHA-256(signature) 와 다르다")
    record = {"chain": CHAIN, "round": rnd, "randomness": first["randomness"], "responses": got}
    out.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    print(f"라운드 {rnd} randomness {first['randomness']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("round")
    r.add_argument("when", help="ISO 8601 시각(시간대 포함)")
    f = sub.add_parser("fetch")
    f.add_argument("round", type=int)
    f.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "round":
        print(round_at(a.when))
    else:
        fetch(a.round, a.out)


if __name__ == "__main__":
    main()
