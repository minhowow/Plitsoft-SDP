"""모델을 부르지 않는 판정자. 해석기 자체를 시험할 때 쓴다(tests 전용)."""

from __future__ import annotations

from policypack.judge.base import Answer, Question, RawAnswer


class FakeJudge:
    """항상 같은 답을 준다. `echo_first_line` 이면 '예'에 코드의 첫 줄을 인용한다."""

    id = "fake"

    def __init__(self, answer: RawAnswer = "아니오", evidence: str = "", echo_first_line: bool = False) -> None:
        self.default = answer
        self.evidence = evidence
        self.echo_first_line = echo_first_line
        self.asked: list[Question] = []

    def ask(self, q: Question) -> Answer:
        self.asked.append(q)
        raw = self.default
        evidence = self.evidence
        if self.echo_first_line and raw == "예" and not evidence:
            # 코드에 실제로 있는 줄을 인용한다 — 근거 관문을 통과하는 '예'
            lines = [ln for ln in q.code.strip().splitlines() if len(ln.strip()) >= 6]
            evidence = lines[0].strip() if lines else ""
        return Answer(raw=raw, evidence=evidence)
