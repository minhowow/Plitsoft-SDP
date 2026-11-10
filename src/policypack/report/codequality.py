"""GitLab Code Quality 보고서(CodeClimate 형식의 부분 집합).

GitLab 은 `artifacts:reports:codequality` 로 받은 파일을 기본 가지의 보고서와 견줘 머지 요청 화면에 새 경고·사라진
경고로 보여 준다(무료 판. 바뀐 줄 옆 표시는 Ultimate). 받는 키는
`description` · `check_name` · `fingerprint` · `severity` · `location.path` · `location.lines.begin` 이다.
SARIF 와 달리 규칙 설명을 실을 자리가 없어서 조문 이름과 개발자에게 할 질문을 `description` 한 줄에 넣는다.

| 여기 | GitLab 이 쓰는 곳 |
|---|---|
| `fingerprint` | 실행 사이에 같은 경고를 알아본다(SARIF 의 partialFingerprints 와 같은 값) |
| `severity` | 검토 필요 → major · 불확실 → minor |
| `location.path` | 저장소 루트에서의 상대 경로. 루트 밖이면 GitLab 이 줄을 찾지 못한다 |
"""

from __future__ import annotations

import json
from pathlib import Path

from policypack.evaluate.engine import EvalResult
from policypack.report.fingerprint import fingerprints
from policypack.report.outcome import Outcome
from policypack.report.paths import rel

SEVERITY = {
    Outcome.NEEDS_REVIEW: "major",
    Outcome.NEEDS_REVIEW_UNCERTAIN: "minor",
}


def build(result: EvalResult, root: Path | None = None, pack_digest: str = "") -> list[dict]:
    fps = fingerprints(result.findings, pack_digest, root)
    out = []
    for f, fp in zip(result.findings, fps, strict=True):
        if f.outcome not in SEVERITY:
            continue
        head = f.title + (" (불확실)" if f.outcome is Outcome.NEEDS_REVIEW_UNCERTAIN else "")
        parts = [head]
        if f.law:
            parts.append(f"근거 {f.law}")
        if f.ask_developer:
            parts.append(f.ask_developer)
        out.append(
            {
                "description": " — ".join(parts),
                "check_name": f"{f.policy}/{f.rule}",
                "fingerprint": fp,
                "severity": SEVERITY[f.outcome],
                "location": {"path": rel(f.file, root), "lines": {"begin": f.line or 1}},
            }
        )
    return out


def dumps(*args, **kwargs) -> str:
    return json.dumps(build(*args, **kwargs), ensure_ascii=False, indent=2)
