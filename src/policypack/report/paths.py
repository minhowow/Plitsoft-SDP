"""보고에 싣는 경로. 네 출력(text·json·SARIF·지문)이 같은 값을 쓴다.

GitHub 코드 스캐닝은 SARIF 의 uri 를 저장소 루트 기준으로 읽는다. 지문에 들어가는
경로가 실행 위치에 따라 달라지면 같은 경고를 다른 경고로 본다. 그래서 한 곳에서 정한다.

- root 아래면 root 기준 상대 경로. `/tmp` 와 `/private/tmp` 처럼 링크로 갈리는 경우를
  위해 한 번 더 resolve 해서 본다.
- root 밖이면 `../` 로 시작하는 상대 경로. 절대 경로를 그대로 내지 않는다.
- 구분자는 늘 `/`.
"""

from __future__ import annotations

import os
from pathlib import Path


def rel(path_str: str | Path, root: Path | None) -> str:
    p = Path(path_str)
    if root is None or not p.is_absolute():
        return p.as_posix()
    if p.is_relative_to(root):
        return p.relative_to(root).as_posix()
    rp, rr = p.parent.resolve() / p.name, root.resolve()
    if rp.is_relative_to(rr):
        return rp.relative_to(rr).as_posix()
    return Path(os.path.relpath(rp, rr)).as_posix()
