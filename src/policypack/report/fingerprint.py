"""판정 하나를 가리키는 안정적인 해시.

SARIF `partialFingerprints` 에 쓴다. 코드 스캐닝이 실행 사이에 같은 경고를 알아보고,
이미 확인한 항목을 다시 올리지 않게 한다.

**줄 번호를 넣지 않는다.** 위아래에 줄 하나만 추가해도 해시가 전부 바뀌면
이미 확인한 경고가 전부 새 경고가 된다. 대신 판정이 걸린 코드 조각을 정규화해서 넣는다.
조각이 그대로면 같은 항목으로 본다.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from policypack.report.outcome import Finding
from policypack.report.paths import rel

_WS = re.compile(r"\s+")

VERSION = "policypack/v1"


def _snippet(path: Path, line: int | None, span: int = 2) -> str:
    """판정 지점 주변 몇 줄. 공백을 정규화해 서식 변화에 흔들리지 않게 한다."""
    if line is None:
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    lo, hi = max(0, line - 1 - span), min(len(lines), line + span)
    return _WS.sub(" ", " ".join(lines[lo:hi])).strip()


def fingerprint(finding: Finding, pack_digest: str = "", root: Path | None = None, occurrence: int = 0) -> str:
    """같은 문제를 같은 값으로 가리킨다.

    팩이 바뀌면 값도 바뀐다. 규칙이 달라졌는데 예전 확인으로 넘기면 안 된다.
    """
    path = Path(finding.file)
    parts = [
        VERSION,
        pack_digest,
        finding.policy,
        finding.rule,
        rel(path, root),
        _snippet(path, finding.line),
    ]
    if finding.scope == "anchor":
        # 판정 단위가 다르다. 같은 줄이라도 file 판정의 지문과 섞이지 않게 한다.
        parts.append("scope=anchor" + (":top-level" if finding.top_level else ""))
    if occurrence:
        # 같은 규칙·파일에서 주변 조각까지 같은 판정이 또 있다. 0 번째는 예전 값 그대로다.
        parts.append(f"#{occurrence}")
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:32]


def fingerprints(findings: list[Finding], pack_digest: str = "", root: Path | None = None) -> list[str]:
    """판정마다 지문. 같은 값이 둘이면 둘째부터 순번을 붙인다.

    순번은 목록 순서가 아니라 (파일, 줄, 규칙) 순서로 매긴다. 판정을 모으는 순서가 바뀌어도
    같은 판정이 같은 지문을 받아야 한다.
    """
    order = sorted(range(len(findings)), key=lambda i: (findings[i].file, findings[i].line or 0, findings[i].ref))
    seen: dict[str, int] = {}
    out = [""] * len(findings)
    for i in order:
        f = findings[i]
        base = fingerprint(f, pack_digest, root)
        n = seen.get(base, 0)
        seen[base] = n + 1
        out[i] = base if n == 0 else fingerprint(f, pack_digest, root, occurrence=n)
    return out
