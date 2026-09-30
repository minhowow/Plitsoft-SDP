"""정책 팩 읽기와 검증.

YAML 1.2 (`ruamel.yaml`) 로 읽는다. pyyaml 은 YAML 1.1 이라 `yes`/`no`/`on`/`off`/`y`/`n`
을 bool 로 강제변환한다. 정책 팩에는 한국어 질문과 `answer: yes` 같은 값이 들어가므로
그 동작은 조용한 버그가 된다.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from policypack.errors import PackError
from policypack.model import PolicyPack, Scope, Strength
from policypack.static.compile import LANGUAGE_GLOBS, REGION_PATTERNS

_yaml = YAML(typ="safe", pure=True)


def pack_location(path: str | Path) -> tuple[Path, Path]:
    """(정책 팩 파일, 그 팩의 폴더). 폴더를 주면 `<폴더>/pack.yaml` 이다. 폴더에는 `_legal/`·`tests/` 가 있다.

    둘을 따로 들고 다닌다. 파일을 폴더로 바꿔 다시 읽으면, 이름이 pack.yaml 이 아닌 팩 대신 옆의 pack.yaml 을
    읽는다(실측: test 가 경고 없이 다른 팩을 시험했고, scan 은 다른 파일의 해시를 적었다)."""
    p = Path(path)
    return (p / "pack.yaml", p) if p.is_dir() else (p, p.parent)


def load_pack(path: str | Path) -> PolicyPack:
    """정책 팩 파일 하나를 읽어 검증한다."""
    p = Path(path)
    if p.is_dir():
        p = p / "pack.yaml"
    if not p.exists():
        raise PackError(f"정책 팩을 찾을 수 없습니다: {p}")
    try:
        raw = _yaml.load(p.read_text(encoding="utf-8"))
    except YAMLError as e:
        raise PackError(f"{p}: YAML 을 읽지 못했습니다\n{e}") from e
    if not isinstance(raw, dict):
        raise PackError(f"{p}: 최상위가 매핑이 아닙니다")
    try:
        return PolicyPack.model_validate(raw)
    except ValidationError as e:
        raise PackError(f"{p}: 정책 팩이 문법에 맞지 않습니다\n{_format_errors(e)}") from e


def pack_digest(path: str | Path) -> str:
    """팩 파일 내용의 sha256 앞 16자. 결과 메타데이터와 지문에 넣어 어느 판본으로 판정했는지 남긴다."""
    p = Path(path)
    if p.is_dir():
        p = p / "pack.yaml"
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def _format_errors(e: ValidationError) -> str:
    lines = []
    for err in e.errors():
        loc = " → ".join(str(x) for x in err["loc"] if x != "__root__")
        lines.append(f"  {loc or '(최상위)'}: {err['msg']}")
    return "\n".join(lines)


# ── validate 명령이 쓰는 경고들 ─────────────────────────────────────────────


def find_unconfirmable_weak(pack: PolicyPack) -> list[str]:
    """약한 정적 대안이 있는데 그것을 확인할 AI 대안이 없는 규칙.

    약한 대안은 AI 대안이 실재하는 줄을 인용해 확인해야 경고를 푼다. 물을 AI 대안이 없으면 그 대안이
    참이어도 늘 불확실로 남는다. 적은 사람의 기대와 다르다.
    """
    out = []
    for pol, rule in pack.iter_rules():
        weak = [p.id for p in rule.compliant_if_any if not p.is_ai and p.strength is Strength.WEAK]
        if weak and not any(p.is_ai for p in rule.compliant_if_any):
            out.append(
                f"정책 {pol.id} / 규칙 {rule.id}: 약한 대안({', '.join(weak)})을 확인할 AI 대안이 없어 "
                f"경고를 풀지 못하고 불확실로 남습니다"
            )
    return out


def find_anchor_without_regions(pack: PolicyPack) -> list[str]:
    """scope: anchor 인데 함수 경계 패턴(compile.REGION_PATTERNS)이 없는 언어를 쓰는 규칙.

    그 언어의 파일은 함수 단위로 나누지 못하고 파일 전체를 한 구역으로 판정한다.
    """
    out = []
    for pol, rule in pack.iter_rules():
        if rule.scope is not Scope.ANCHOR:
            continue
        missing = [lang for lang in pack.languages_for(rule) if lang not in REGION_PATTERNS]
        if missing:
            out.append(
                f"정책 {pol.id} / 규칙 {rule.id}: {', '.join(missing)} 에는 함수 경계 패턴이 없어 "
                f"scope: anchor 여도 파일 전체를 한 구역으로 판정합니다"
            )
    return out


def find_unselected_languages(pack: PolicyPack) -> list[str]:
    """폴더 검사가 파일을 고르지 않는 언어(compile.LANGUAGE_GLOBS 에 없음)를 쓰는 규칙.

    Semgrep 이 아는 언어여도(rust 등) 폴더를 검사하면 그 언어의 파일은 대상에 들지 않는다. 이름을 댄 파일만
    검사되어 같은 파일의 판정이 부르는 법에 따라 달라진다(검토에서 실측)."""
    out = []
    for pol, rule in pack.iter_rules():
        missing = [lang for lang in pack.languages_for(rule) if lang not in LANGUAGE_GLOBS]
        if missing:
            out.append(
                f"정책 {pol.id} / 규칙 {rule.id}: {', '.join(missing)} 파일은 폴더 검사에서 고르지 않습니다 "
                f"(이름을 댄 파일만 검사합니다)"
            )
    return out


def check_legal_texts(pack: PolicyPack, base: Path) -> list[str]:
    """조문 원문 파일의 해시를 확인한다.

    원격 페이지가 아니라 커밋된 파일을 검사하므로, 법제처 사이트가 바뀌어도
    깨지지 않는다. 해시가 없는 조문은 '미완'으로 드러낸다.
    """
    out: list[str] = []
    for pol in pack.policies:
        if pol.legal is None:
            out.append(f"정책 {pol.id}: legal 이 없습니다. 근거 조문 없이 경고를 냅니다")
            continue
        for ref in pol.legal.violated_when_failed:
            label = f"정책 {pol.id} / {ref.statute} {ref.article}"
            if not ref.text_file:
                out.append(f"{label}: 조문 원문 파일이 없습니다 (추적성 미완)")
                continue
            f = base / ref.text_file
            if not f.exists():
                out.append(f"{label}: 원문 파일이 없습니다 — {ref.text_file}")
                continue
            if not ref.text_sha256:
                out.append(f"{label}: text-sha256 이 비어 있습니다 (추적성 미완)")
                continue
            actual = hashlib.sha256(f.read_bytes()).hexdigest()
            if actual != ref.text_sha256:
                out.append(
                    f"{label}: 원문이 바뀌었습니다. 조문을 다시 확인하고 규칙을 손봐야 합니다\n"
                    f"    기록된 해시: {ref.text_sha256}\n"
                    f"    실제 해시  : {actual}"
                )
    return out


def check_review_dates(pack: PolicyPack, today: Any = None) -> list[str]:
    """재검토 기한이 지난 정책을 찾는다."""
    import datetime as dt

    today = today or dt.date.today()
    out = []
    for pol in pack.policies:
        if pol.review is None:
            out.append(f"정책 {pol.id}: 재검토 기한(review.review-by)이 없습니다")
        elif pol.review.review_by < today:
            days = (today - pol.review.review_by).days
            out.append(f"정책 {pol.id}: 재검토 기한이 {days}일 지났습니다 ({pol.review.review_by})")
    return out
