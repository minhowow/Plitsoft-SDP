"""기본 정책 팩이 어디 있는지.

`scan` 의 기본 경로가 현재 폴더 기준(`policies/kr-core`)이면, pre-commit 훅처럼
**사용자 저장소에서 돌릴 때 팩을 못 찾는다.** 그 저장소에는 policies/ 가 없으니까.
그래서 순서를 정해 찾는다.

1. 환경변수 `POLICYPACK_PACK` — 명시한 것이 가장 세다
2. 이 소스 저장소 (개발 중, 편집 가능 설치)
3. 패키지에 실린 사본 (`policypack/_bundled/`, 휠로 설치했을 때)

배포 휠에는 pyproject 의 force-include 로 policies/kr-core 가 실린다.
"""

from __future__ import annotations

import os
from pathlib import Path

_PKG = Path(__file__).resolve().parent
_REPO = _PKG.parents[1]  # src/policypack → 저장소 루트 (편집 가능 설치일 때)
_BUNDLED = _PKG / "_bundled"


def _first(*candidates: Path) -> Path | None:
    for c in candidates:
        if c.exists():
            return c
    return None


def default_pack() -> Path:
    env = os.environ.get("POLICYPACK_PACK")
    if env:
        return Path(env)
    found = _first(_REPO / "policies" / "kr-core", _BUNDLED / "policies" / "kr-core")
    return found or Path("policies/kr-core")
