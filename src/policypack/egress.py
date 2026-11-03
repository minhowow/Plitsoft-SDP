"""외부 전송 통제 — 코드가 모델 API 로 나가기 전에 비밀값을 가리고, 비밀값 파일은 읽지 않는다.

에이전트형 판정기는 도구로 읽은 파일 내용을 모델에게 보낸다. 사용자의 저장소에는 키·토큰·개인키가 들어 있을 수
있다(.env 를 커밋한 저장소도 흔하다). 그래서 도구의 결과가 나가기 전에 이 모듈을 거친다.

가리는 것
  - 개인키 블록, 알려진 키 모양(AWS·GitHub·Slack·Google·OpenAI·Anthropic·Stripe 등), JWT
  - 비밀처럼 이름 붙은 변수에 넣은 긴 문자열(password·secret·token·api_key 등)
  - 주민등록번호 모양, 카드 번호 모양(Luhn 검사를 통과하는 것만)
가리지 않는 것
  - 전화번호·이메일·회사 이름. 광고 전송자의 연락처처럼 의무를 이행하는 근거가 되는 글이라 가리면 인용 관문을
    통과할 수 없다. 이것이 이 모듈의 한계다(보고서와 docs 에 적는다).
읽지 않는 파일
  - `.env`, `.env.local` 같은 환경 파일(`.env.example`·`.sample`·`.template` 은 읽는다), `*.pem`·`*.key`·`id_rsa`

가린 자리는 `[가림:<종류>]` 로 바꾼다. 가린 수는 전송 기록에 남는다.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S)),
    ("aws-key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b")),
    ("slack-token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b")),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("api-key", re.compile(r"\b(sk|rk|pk)[-_](live|test|ant|proj)?[-_]?[A-Za-z0-9_-]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("rrn", re.compile(r"(?<!\d)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])-?[1-4]\d{6}(?!\d)")),
]
_ASSIGN = re.compile(
    r"""(?ix)
    \b([\w.-]*(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret)[\w.-]*)
    (\s*["']?\s*[:=]\s*)
    (["'`])([^"'`\s]{8,})\4
    """
)
_CARD = re.compile(r"(?<!\d)(\d{4})[- ]?(\d{4})[- ]?(\d{4})[- ]?(\d{4})(?!\d)")
_SECRET_FILE = re.compile(r"(^|/)(\.env(\.[\w-]+)?|[^/]+\.(pem|key|p12|pfx)|id_(rsa|dsa|ecdsa|ed25519))$", re.I)
_ENV_OK = re.compile(r"\.(example|sample|template|dist|defaults?)$", re.I)


def is_secret_file(rel: str) -> bool:
    """읽지 않을 파일인가. `rel` 은 저장소 기준 경로."""
    name = PurePosixPath(rel).name
    return bool(_SECRET_FILE.search(rel)) and not _ENV_OK.search(name)


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def mask(text: str) -> tuple[str, dict[str, int]]:
    """가린 글과 종류별 가린 수."""
    counts: dict[str, int] = {}

    def sub(kind: str, rx: re.Pattern, s: str) -> str:
        def repl(m: re.Match) -> str:
            counts[kind] = counts.get(kind, 0) + 1
            return f"[가림:{kind}]"

        return rx.sub(repl, s)

    for kind, rx in _PATTERNS:
        text = sub(kind, rx, text)

    def assign(m: re.Match) -> str:
        if m.group(5).startswith("[가림:") or m.group(5).lower() in {"password", "undefined", "process.env"}:
            return m.group(0)
        counts["secret-value"] = counts.get("secret-value", 0) + 1
        return f"{m.group(1)}{m.group(3)}{m.group(4)}[가림:secret-value]{m.group(4)}"

    text = _ASSIGN.sub(assign, text)

    def card(m: re.Match) -> str:
        digits = "".join(m.groups())
        if not _luhn(digits) or len(set(digits)) == 1:
            return m.group(0)
        counts["card"] = counts.get("card", 0) + 1
        return "[가림:card]"

    text = _CARD.sub(card, text)
    return text, counts
