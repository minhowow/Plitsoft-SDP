"""파일 역할. 경로와 내용의 모양으로 하나를 고른다.

역할은 후보를 고르는 힌트다. 판정의 근거가 아니다. 그래서 틀려도 경고를 지우는 쪽으로 쓰이지 않게 한다
(예: '시험' 역할 파일도 검사 대상에서 빼지 않는다 — discover.py 의 첫 문단).

  test     시험·스토리·목업. 경로 이름으로만 고른다
  config   설정 파일(*.config.*, .eslintrc 등)
  server   화면이 없는 서버 쪽 처리(API 라우트, 서버 액션, express·nest 등)
  screen   이용자가 보는 화면(JSX 를 내는 파일, pages·app 라우트의 화면 파일)
  other    위 어디에도 들지 않는 모듈(유틸, 훅, 상태, 클라이언트 API 등)
"""

from __future__ import annotations

import re
from enum import Enum


class Role(str, Enum):
    TEST = "test"
    CONFIG = "config"
    SERVER = "server"
    SCREEN = "screen"
    OTHER = "other"


_TEST_PATH = re.compile(
    r"(^|/)(__tests__|__mocks__|__fixtures__|tests?|e2e|cypress|playwright|mocks?|fixtures?|stories|storybook)/"
    r"|\.(test|spec|stories|story|e2e|cy)\.[cm]?[jt]sx?$",
    re.I,
)
_CONFIG_PATH = re.compile(
    r"(^|/)(\.?[\w.-]*rc\.[cm]?[jt]s|[\w.-]+\.config\.[cm]?[jt]s|\.eslintrc[\w.]*|gulpfile\.[jt]s|gruntfile\.[jt]s)$",
    re.I,
)
_SERVER_PATH = re.compile(
    r"(^|/)(pages/api|app/api|server|servers|backend|functions|lambda|routes?|controllers?|middlewares?|"
    r"services?/server)/|(^|/)route\.[cm]?[jt]s$|(^|/)middleware\.[cm]?[jt]s$|\.server\.[cm]?[jt]sx?$",
    re.I,
)
_SERVER_CODE = re.compile(
    r"""^\s*['"]use server['"]|\bexpress\s*\(|\bRouter\s*\(|\bNextResponse\b|\bNextApiRequest\b|"""
    r"""@nestjs/|\bfastify\s*\(|\bnew\s+Hono\b|\bkoa\b.*require|from\s+['"]koa['"]|"""
    r"""\bexport\s+(async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE)\b|\bonRequest\w*\s*\(|functions\.https""",
    re.M,
)
_JSX = re.compile(r"<[A-Za-z][\w.]*(\s[^<>]*)?/?>|return\s*\(\s*<|\bReact\.createElement\b|\bh\(\s*['\"]\w")
_SCREEN_PATH = re.compile(
    r"(^|/)(pages|app|screens?|views?|components?|layouts?|templates?)/|\.(vue|svelte)$|(^|/)(page|layout)\.[jt]sx$",
    re.I,
)


def classify(rel: str, text: str) -> Role:
    """`rel` 은 저장소 기준 '/' 경로, `text` 는 파일 내용(앞부분만 줘도 된다)."""
    if _TEST_PATH.search(rel):
        return Role.TEST
    if _CONFIG_PATH.search(rel):
        return Role.CONFIG
    jsx = rel.endswith((".jsx", ".tsx")) and bool(_JSX.search(text))
    if _SERVER_CODE.search(text) and not jsx:
        return Role.SERVER
    if _SERVER_PATH.search(rel) and not jsx:
        return Role.SERVER
    if jsx:
        return Role.SCREEN
    if _SCREEN_PATH.search(rel) and rel.endswith((".jsx", ".tsx", ".vue", ".svelte")):
        return Role.SCREEN
    return Role.OTHER
