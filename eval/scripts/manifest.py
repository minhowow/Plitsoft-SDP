#!/usr/bin/env python3
"""파일·폴더의 SHA-256 목록을 낸다. 고정 기록(eval/freeze/)에 남길 글이다.

    manifest.py PATH [PATH ...]

폴더는 안의 파일을 경로 순으로 하나씩 적는다. 마지막 줄은 목록 전체의 해시다.
"""

import hashlib
import sys
from pathlib import Path


def files(p: Path):
    if p.is_file():
        yield p
    else:
        yield from sorted(f for f in p.rglob("*") if f.is_file() and ".git" not in f.parts and f.name != ".DS_Store")


lines = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f}" for arg in sys.argv[1:] for f in files(Path(arg))]
print("\n".join(lines))
print(f"{hashlib.sha256(chr(10).join(lines).encode('utf-8')).hexdigest()}  (위 {len(lines)}줄 전체)")
