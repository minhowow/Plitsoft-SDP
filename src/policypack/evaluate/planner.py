"""판정 규칙 — 언제 AI 에게 묻고, 무엇을 판정에 넣는가. 부르지는 않는다.

엔진(evaluate)과 정책 테스트의 커버리지 계산(packtest)이 이 함수들을 함께 쓴다. 두 곳에 같은 규칙을
따로 적으면 언젠가 어긋난다.

- 적용: 정적 적용 조건이 '모름'(파싱 실패 등)이고 applies-ai 가 있을 때만 묻는다. 적용 질문의 '아니오'는
  인용 없이 규칙을 끄는 답이라, 정적으로 결론이 난 곳에서는 묻지 않는다.
- 대안: **강한** 정적 대안이 참이면 묻지 않는다. 약한 정적 대안(이름·문자열만 본 조건)만 참이면 AI 가
  재확인한다. 약한 근거는 경고를 풀지 못한다 — 판정자가 없으면 '모름'으로 남는다.
"""

from __future__ import annotations

from policypack.evaluate.kleene import FALSE, TRUE, UNKNOWN, Tri, clear_only
from policypack.model import Strength
from policypack.report.outcome import Outcome


def needs_applicability_question(applies: Tri, has_question: bool) -> bool:
    """적용을 AI에게 물어야 하는가. 정적 적용 판단이 결론을 내지 못했을 때만이다."""
    return has_question and applies is UNKNOWN


def needs_alternative_questions(alts: list[tuple]) -> bool:
    """대안을 AI에게 물어야 하는가. 강한 정적 대안이 하나라도 참이면 묻지 않는다."""
    return not any(
        kind == "static" and value is TRUE and pred.strength is Strength.STRONG for kind, pred, value in alts
    )


def considered_values(alts: list[tuple], ai_values: list[Tri], answered: bool) -> list[Tri]:
    """준수 판정에 넣을 값들.

    `answered` 는 물은 AI 대안에 모두 답을 받았는가다.

    - 받았으면 약한 정적 대안의 값은 AI 답으로 **대체**한다(판정에 넣지 않는다). 이름만 보고 참이 된 것을
      그대로 두면 재확인이 무의미해진다.
    - 받지 못했으면(판정자가 없거나, 일부가 실패했거나 쓸 수 없는 답이었거나, 규칙에 AI 대안이 없으면) 약한
      정적 대안의 '참'은 '모름'으로 낮춘다. 버리면 판정자가 일부만 실패했을 때가 없을 때보다 센 결론(확실한 검토
      필요)을 낸다.
    """
    static_values = [
        clear_only(value) if pred.strength is Strength.WEAK else value
        for kind, pred, value in alts
        if kind == "static" and not (answered and pred.strength is Strength.WEAK)
    ]
    return static_values + list(ai_values)


def decide(applies: Tri, compliant: Tri) -> Outcome:
    """판정 하나.

    적용이 '모름'인 채로 준수가 확정되지 않으면 불확실이다. 법률 판정이 아니라
    사람이 볼 지점을 고르는 것이므로, 애매하면 남긴다.
    """
    if applies is UNKNOWN and compliant is not TRUE:
        return Outcome.NEEDS_REVIEW_UNCERTAIN
    if compliant is TRUE:
        return Outcome.COMPLIANT
    if compliant is FALSE:
        return Outcome.NEEDS_REVIEW
    return Outcome.NEEDS_REVIEW_UNCERTAIN
