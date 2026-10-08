"""판정 결과와 그 이유.

판정은 열거형이다. 보고 문구를 고쳐도 종료 코드와 정책 테스트의 채점이 바뀌지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Outcome(str, Enum):
    COMPLIANT = "compliant"
    """적법한 대안이 확인됐다."""

    NEEDS_REVIEW = "needs-review"
    """적용되는데 대안이 하나도 없다. 사람이 봐야 한다."""

    NEEDS_REVIEW_UNCERTAIN = "needs-review-uncertain"
    """결론이 안 났다(적용이나 대안이 '모름'). 경고로 보고하되 `--fail-on review` 는 종료 코드에 넣지 않는다."""

    NOT_APPLICABLE = "not-applicable"
    """적용 조건이 거짓이다. 엔진은 이 판정을 Finding 으로 내지 않는다(정책 테스트의 기대 값으로 쓴다)."""

    @property
    def is_finding(self) -> bool:
        """사용자에게 보여 줄 항목인가."""
        return self in (Outcome.NEEDS_REVIEW, Outcome.NEEDS_REVIEW_UNCERTAIN)


class UntestedReason(str, Enum):
    """판정을 끝까지 하지 못한 이유. 판정 종류와 상관없이 붙고, 여럿이 쌓일 수 있다."""

    PARSE_ERROR = "parse-error"
    ENGINE_INCOMPLETE = "engine-incomplete"
    """엔진이 이 파일에서 규칙을 끝내지 못했거나 함수 경계를 얻지 못했다(시간 초과·메모리 부족 등). 파일 문법
    문제가 아니다."""
    NO_JUDGE = "no-judge"
    """AI 에게 물어야 할 곳인데 판정자가 꺼져 있다(기본값 --judge none)."""
    JUDGE_UNAVAILABLE = "judge-unavailable"
    """판정자를 부르지 못했다(연결·인증 실패 등)."""
    JUDGE_UNPARSEABLE = "judge-unparseable"
    """판정자가 답했지만 쓸 수 없었다(형식 오류, 도구를 쓰려 한 격리 위반, 대안 질문에 '해당없음'·'모름')."""
    CITATION_REJECTED = "citation-rejected"
    """판정자가 '예'라고 했지만 근거 관문이 인용을 받지 않았다(코드에 없음·주석뿐·낱말 하나 등)."""
    WEAK_UNCONFIRMED = "weak-unconfirmed"
    """이름·문자열만 본 약한 대안이 참인데, 이 규칙에는 확인할 AI 대안이 없어 풀지 않았다."""
    TIMEOUT = "timeout"
    """판정자가 시간 안에 답하지 않았다."""


def reason_for_failure(failure: str | None) -> UntestedReason:
    """판정자가 쓸 만한 답을 주지 못한 이유 → 보고할 이유.

    그 밖(transport, 스텁 없음 missing)은 판정자를 부르지 못한 것으로 본다."""
    return {
        "timeout": UntestedReason.TIMEOUT,
        "parse": UntestedReason.JUDGE_UNPARSEABLE,
        "isolation": UntestedReason.JUDGE_UNPARSEABLE,
    }.get(failure or "", UntestedReason.JUDGE_UNAVAILABLE)


@dataclass
class Finding:
    policy: str
    rule: str
    outcome: Outcome
    file: str
    case: str | None = None
    category: str = ""
    title: str = ""
    law: str = ""
    ask_developer: str = ""
    line: int | None = None
    untested_reasons: list[UntestedReason] = field(default_factory=list)
    ai_pending: list[str] = field(default_factory=list)
    """AI 에게 물어야 했는데 판정에 넣을 답이 없는 조건 id. 판정자가 없거나, 답하지 못했거나, 쓸 수 없는 답(관문이
    받지 않은 '예', '해당없음'·'모름')이었다. 판정에 넣지 않으므로 정적 판정이 그대로 남는다."""
    trace: list[str] = field(default_factory=list)
    alternatives: list[dict] = field(default_factory=list)
    scope: str = "file"
    region: tuple[int, int] | None = None
    """scope: anchor 의 판정 구역(감싸는 가장 바깥 함수)의 줄 범위. None 이면 파일 전체."""
    anchor_lines: list[int] = field(default_factory=list)
    """같은 구역 안의 모든 앵커 줄. 첫 줄이 line 이다."""
    top_level: bool = False
    """판정 구역이 함수 밖(모듈 최상위)의 줄이다. region 은 None 이다."""

    @property
    def ref(self) -> str:
        return f"{self.policy}/{self.rule}"
