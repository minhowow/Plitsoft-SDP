"""근거 관문 — AI가 경고를 해제할 자격이 있는지 본다.

AI의 "예, 적법한 대안이 있다"는 **코드에 실제로 있는 코드를 인용할 때만** 인정한다. 인용은 코드에 글자 그대로
(공백만 느슨하게) 있는 6자 이상의 연속된 조각이어야 하고, 줄 전체가 아닌 낱말 하나(`router`, `prisma`)는 받지
않는다. 관문은
인용이 코드에 있는지만 본다 — 그 줄이 질문과 관련 있는지는 보지 않는다. 그래서 AI 가 푼 경고는 인용과 함께
보고서에 남는다.
관문이 받지 않은 '예'는 '거짓'이 되지 않고 판정에서 빠져(판정자가 없을 때처럼) 경고가 남는다. 이 비대칭이
방향성 신뢰의 핵심이다 — 약한 근거는 경고를 올릴 수는 있어도 내릴 수는 없다.

주석은 실행되지 않으므로 대안의 존재를 입증하지 못한다. 주석에서만 찾은 인용은 떨어진다.
줄 끝에 주석이 붙은 코드 줄을 인용하면 주석을 뗀 나머지가 실행되는 코드에 있어야 한다
(`ensureMinorPolicy(...) // 만 14세 미만 차단` 처럼 그 함수가 하는 일을 주석만 말해 주는 경우).

인용 **전체**가 먼저 코드에 있어야 한다. 인용만 떼어 주석을 걷으면 따옴표 없이 인용한 URL 의
`//` 뒤가 잘려 `https:` 만 남고, 코드 어딘가의 `"https://..."` 에 맞아 지어낸 URL 도 통과한다.
"""

from __future__ import annotations

import re
from enum import Enum

MIN_LENGTH = 6
"""인용이 이보다 짧으면 버린다. `}` 나 `true` 같은 것은 아무것도 입증하지 못한다."""

_WS = re.compile(r"\s+")
_WORD = re.compile(r"[\w$]+")


class GateResult(str, Enum):
    GROUNDED = "grounded"
    """실행되는 코드에서 찾았다. 경고를 해제할 수 있다."""

    TRAILING_COMMENT = "trailing-comment"
    """코드 줄에서 찾았지만 인용이 그 줄의 주석 부분에 걸쳐 있다."""

    COMMENT_ONLY = "comment-only"
    """주석에서만 찾았다. 주석은 실행되지 않는다."""

    NOT_FOUND = "not-found"
    """코드에 없다. 지어냈거나 고쳐 쓴 것이다."""

    TOO_SHORT = "too-short"
    BARE_WORD = "bare-word"
    """낱말 하나인데 코드 줄 전체도 아니다. 식별자 이름은 무엇도 입증하지 못한다(실측: `router` 로 경고가 풀렸다).
    줄 전체가 그 낱말이면(JSX 글자 줄 `AI생성요약`) 받는다."""
    EMPTY = "empty"


def _norm(s: str) -> str:
    """공백을 한 칸으로 줄이고 양끝의 따옴표·백틱을 뗀다. 인용과 코드를 같은 꼴로 맞춰 비교한다."""
    return _WS.sub(" ", s).strip().strip("`'\"")


def strip_comments(code: str) -> str:
    """주석을 같은 길이의 공백으로 바꾼다. JS·TS 계열의 `//`·`/* */` 주석만 안다.

    길이를 유지해야 원래 코드와 위치를 맞출 수 있다. 문자열 안의 `//` 는 주석이
    아니므로(예: `"https://..."`) 문자열을 따라가며 읽는다.
    """
    out = list(code)
    i, n = 0, len(code)
    quote: str | None = None
    while i < n:
        ch = code[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            if code[i + 1] == "/":
                j = code.find("\n", i)
                j = n if j < 0 else j
                out[i:j] = " " * (j - i)
                i = j
                continue
            if code[i + 1] == "*":
                j = code.find("*/", i + 2)
                j = n if j < 0 else j + 2
                for k in range(i, j):
                    if code[k] != "\n":
                        out[k] = " "
                i = j
                continue
        i += 1
    return "".join(out)


def classify(evidence: str, code: str, stripped: str | None = None) -> GateResult:
    """인용이 코드의 어디에서 나왔는지 가른다.

    `stripped` 는 주석을 이미 걷어 낸 같은 코드다. 코드가 파일의 일부(판정 구역)면 주석은 파일
    전체에서 걷어 낸 뒤 잘라서 넘겨야 한다. 조각만 걷으면 조각 앞의 짝 없는 따옴표를 모르고
    주석을 코드로, 코드를 주석으로 읽는다(검토에서 실측).
    """
    if not evidence or not evidence.strip():
        return GateResult.EMPTY
    ev = _norm(evidence)
    if len(ev) < MIN_LENGTH:
        return GateResult.TOO_SHORT
    if ev not in _norm(code):
        return GateResult.NOT_FOUND

    without = stripped if stripped is not None else strip_comments(code)
    if _WORD.fullmatch(ev) and ev not in {_norm(line) for line in without.splitlines()}:
        return GateResult.BARE_WORD
    if ev in _norm(without):
        return GateResult.GROUNDED

    # 주석을 걷어내니 사라졌다. 줄 단위로 보아 주석에만 있었는지,
    # 코드 줄 끝의 주석에 걸쳐 있었는지 가른다.
    for raw, bare in zip(code.splitlines(), without.splitlines(), strict=True):
        if ev in _norm(raw):
            # 줄 끝 주석이 붙은 코드 줄을 인용했는가, 그 줄의 주석 글만 인용했는가
            code_part = _norm(strip_comments(evidence))
            return GateResult.TRAILING_COMMENT if code_part and code_part in _norm(bare) else GateResult.COMMENT_ONLY
    return GateResult.TRAILING_COMMENT


def is_grounded(evidence: str, code: str, strict: bool = False, stripped: str | None = None) -> bool:
    """이 인용으로 경고를 해제해도 되는가.

    인용 전체가 코드에 있어야 한다. 실행되는 코드에서 찾으면 인정하고, 주석에서만 찾으면 떨어진다.
    줄 끝에 주석이 달린 줄을 인용했으면 인용에서 주석을 떼고 남은 코드 부분이 실행되는 코드에 있을 때
    인정한다. `strict`(evidence: strict)면 인용을 한 글자도 고치지 않고 주석 없는 코드에서 찾는다 —
    줄 끝 주석이 붙은 인용도 떨어진다.
    """
    where = classify(evidence, code, stripped)
    if where is GateResult.GROUNDED:
        return True
    if strict or where is not GateResult.TRAILING_COMMENT:
        return False  # 코드에 없거나(지어냄) 주석에만 있다
    bare_evidence = strip_comments(evidence)
    if len(_norm(bare_evidence)) < MIN_LENGTH:
        return False  # 인용에서 주석을 떼면 남는 게 없다 = 주석만 인용했다
    bare_code = stripped if stripped is not None else strip_comments(code)
    return classify(bare_evidence, bare_code, stripped=bare_code) is GateResult.GROUNDED
