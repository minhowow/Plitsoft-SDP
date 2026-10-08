"""사람이 읽는 출력.

출력의 성격이 도구의 성격이다. 이건 "위반이다"가 아니라 **"여기를 검토하라"**이다.
그래서 판정마다 셋을 함께 낸다.

1. 어느 적법한 대안이 왜 안 맞았는지 (대안마다 따로)
2. 개발자에게 할 구체적인 질문
3. 근거 조문

법률 자문이 아니라는 말은 요약 끝에 한 번 붙인다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from policypack.discover import SKIPPED_REASONS
from policypack.evaluate.engine import EvalResult
from policypack.report.outcome import Finding, Outcome
from policypack.report.paths import rel

LABEL = {
    Outcome.NEEDS_REVIEW: "검토 필요",
    Outcome.NEEDS_REVIEW_UNCERTAIN: "검토 필요(불확실)",
    Outcome.COMPLIANT: "충족 근거 발견",
}

UNTESTED_WHY = {
    "parse-error": "파일을 파싱하지 못했습니다",
    "engine-incomplete": "엔진이 이 파일에서 규칙을 끝내지 못했거나 함수 경계를 얻지 못했습니다",
    "no-judge": "AI 에게 물어야 할 곳인데 판정자가 꺼져 있습니다(--judge)",
    "judge-unavailable": "판정자를 부르지 못했습니다",
    "judge-unparseable": "판정자의 답을 쓸 수 없었습니다(형식 오류·격리 위반·예/아니오가 아닌 답)",
    "citation-rejected": "판정자가 '예'라고 했지만 인용을 코드에서 확인하지 못했습니다",
    "weak-unconfirmed": "이름만 본 약한 근거라 AI 확인 없이는 풀지 않았습니다(이 규칙에는 AI 대안이 없습니다)",
    "timeout": "판정자가 시간 안에 답하지 않았습니다",
}


class Style:
    def __init__(self, enabled: bool) -> None:
        self.on = enabled

    def _w(self, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if self.on else s

    def bold(self, s):  # noqa: D102
        return self._w("1", s)

    def dim(self, s):  # noqa: D102
        return self._w("2", s)

    def warn(self, s):  # noqa: D102
        return self._w("33", s)

    def soft(self, s):  # noqa: D102
        return self._w("36", s)

    def ok(self, s):  # noqa: D102
        return self._w("32", s)


def use_color(stream=None) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    stream = stream or sys.stdout
    return bool(getattr(stream, "isatty", lambda: False)())


def render(result: EvalResult, root: Path | None = None, explain: bool = False, color: bool | None = None) -> str:
    st = Style(use_color() if color is None else color)
    out: list[str] = []

    order = {Outcome.NEEDS_REVIEW: 0, Outcome.NEEDS_REVIEW_UNCERTAIN: 1}
    findings = sorted(
        result.findings,
        key=lambda f: (order.get(f.outcome, 9), f.file, f.line or 0, f.policy),
    )

    for f in findings:
        out.append("")
        out.append(_head(f, st, root))
        out.extend(_body(f, st))
        if explain:
            out.append(st.dim("  판정 경로"))
            out.extend(st.dim(f"    {line}") for line in f.trace)

    if explain:
        out.extend(_ai_decisions(result, st, root))

    out.append("")
    out.append(_summary(result, findings, st, root))
    return "\n".join(out)


def _head(f: Finding, st: Style, root: Path | None) -> str:
    path = rel(f.file, root)
    where = f"{path}:{f.line}" if f.line else path
    tag = LABEL.get(f.outcome, f.outcome.value)
    paint = st.warn if f.outcome is Outcome.NEEDS_REVIEW else st.soft
    return f"{st.bold(where)}  {paint(tag)}  {f.title}"


def _body(f: Finding, st: Style) -> list[str]:
    lines = []
    if f.law:
        lines.append(st.dim(f"    근거  {f.law}"))
    if f.scope == "anchor":
        where = f"{f.region[0]}~{f.region[1]}행 함수" if f.region else ("함수 밖" if f.top_level else "파일 전체")
        more = f.anchor_lines[1:]
        extra = f" · 같은 구역의 다른 위치 {', '.join(map(str, more))}행" if more else ""
        lines.append(st.dim(f"    판정 구역  {where}{extra}"))
    reasons = f.untested_reasons
    if reasons:
        # 판정 종류와 상관없이 보인다. 다 판정하지 못한 이유는 대개 '불확실' 판정에 붙는다
        why = " · ".join(UNTESTED_WHY.get(r.value, r.value) for r in reasons)
        lines.append(st.soft(f"    다 판정하지 못함  {why}"))
    if f.ai_pending:
        lines.append(st.soft(f"    AI 확인 필요  {', '.join(f.ai_pending)} — 판정에 넣지 않았습니다"))

    for alt in f.alternatives:
        lines.append(f"    · {alt['message']}")
        if alt.get("ask_developer"):
            lines.append(st.dim(f"      → {alt['ask_developer']}"))
        if alt.get("remediation"):
            lines.append(st.dim(f"      고치려면: {alt['remediation']}"))

    if f.ask_developer and not any(a.get("ask_developer") for a in f.alternatives):
        lines.append(st.dim(f"    확인 질문  {f.ask_developer}"))
    return lines


def pending_note(result: EvalResult, hint: bool = False) -> str:
    """'AI 확인이 필요한 곳' 한 줄. 약한 근거만으로는 경고를 풀지 않는다는 것도 함께 알린다."""
    if result.judge_id:
        why = "판정자가 답하지 못했거나 쓸 수 없는 답이었습니다"
    else:
        why = "판정자가 꺼져 있습니다" + (". --judge 로 켜면 AI 가 확인합니다" if hint else "")
    tail = "(이름만 본 약한 근거로는 풀지 않습니다)"
    return f"AI 확인이 필요한 곳 {result.ai_pending}건 — {why}. 경고로 남았습니다{tail}"


def _ai_decisions(result: EvalResult, st: Style, root: Path | None) -> list[str]:
    """AI 가 풀거나 뺀 판정. 관문은 인용이 코드에 있는지만 보므로 사람이 검토할 수 있어야 한다."""
    out: list[str] = []
    if result.ai_cleared:
        out.append("")
        out.append(st.bold("AI 가 해제한 경고") + st.dim("  인용한 줄이 이 규칙의 근거인지 확인하세요"))
        for c in result.ai_cleared:
            where = rel(c["file"], root) + (f":{c['line']}" if c.get("line") else "")
            out.append(f"  {where}  {c['policy']}/{c['rule']}")
            for alt in c["alternatives"]:
                out.append(st.dim(f"    {alt['id']}: “{alt['cite']}” ({alt['gate']})"))
    if result.ai_dismissed:
        out.append("")
        out.append(st.bold("AI 가 '해당 없음'으로 뺀 판정") + st.dim("  인용 없이 빠졌습니다"))
        for d in result.ai_dismissed:
            where = rel(d["file"], root) + (f":{d['line']}" if d.get("line") else "")
            out.append(f"  {where}  {d['policy']}/{d['rule']}")
            out.append(st.dim(f"    질문: {d['question']} → {d['answer']}"))
    return out


def _unit_key(u) -> tuple:
    region = (u.region.start.line, u.region.end.line) if u.region else None
    return (u.policy.id, u.rule.id, str(u.target.path.resolve()), region, u.top_level)


def _summary(result: EvalResult, findings: list[Finding], st: Style, root: Path | None = None) -> str:
    counts: dict[Outcome, int] = {}
    for f in findings:
        counts[f.outcome] = counts.get(f.outcome, 0) + 1
    parts = [f"{LABEL[o]} {counts[o]}" for o in (Outcome.NEEDS_REVIEW, Outcome.NEEDS_REVIEW_UNCERTAIN) if counts.get(o)]
    # 해석기가 판정한 단위 중 경고가 없는 것.
    # scope: anchor 면 한 파일에 판정 단위가 여럿이다. 구역까지 열쇠에 넣는다.
    flagged_units = {(f.policy, f.rule, str(Path(f.file).resolve()), f.region, f.top_level) for f in findings}
    compliant = sum(1 for u in result.units if _unit_key(u) not in flagged_units)
    if compliant > 0:
        # '준수'라고 적지 않는다. 도구가 본 것은 대안 하나를 채우는 근거이고, 법을 지켰는지는 사람이 정한다
        parts.append(st.ok(f"충족 근거 발견 {compliant}"))
    if not parts:
        parts = [st.ok("검토할 것 없음")]

    cost = f"{result.engine or '정적'} {result.static_seconds:.1f}초"
    if result.questions_asked:
        cost += (
            f" · AI 질문 {result.questions_asked}개(보낸 것 {result.questions_sent}개 · 답 {result.ai_answered}) "
            f"{result.ai_seconds:.1f}초"
        )
    else:
        cost += " · AI 0회"

    body = f"{st.bold('요약')}  {' · '.join(parts)}  ({cost})"
    gaps = []
    if result.ai_pending:
        gaps.append("  " + pending_note(result, hint=True))
    if result.ai_cleared:
        gaps.append(
            f"  AI 가 해제한 경고 {len(result.ai_cleared)}건 — 인용한 줄을 확인하세요(--explain 또는 full 출력)"
        )
    if result.ai_dismissed:
        gaps.append(f"  AI 가 '해당 없음'으로 뺀 판정 {len(result.ai_dismissed)}건 — 인용 없이 빠졌습니다")
    if result.unparsed:
        names = ", ".join(rel(p, root) for p in result.unparsed[:3])
        more = f" 외 {len(result.unparsed) - 3}개" if len(result.unparsed) > 3 else ""
        gaps.append(
            f"  파싱하지 못한 파일 {len(result.unparsed)}개({names}{more}) — 구문 조건을 확인하지 못해 "
            f"'불확실'로 남았을 수 있습니다"
        )
    if result.incomplete:
        names = ", ".join(rel(p, root) for p in result.incomplete[:3])
        more = f" 외 {len(result.incomplete) - 3}개" if len(result.incomplete) > 3 else ""
        gaps.append(
            f"  엔진이 끝내지 못한 파일 {len(result.incomplete)}개({names}{more}) — 정책 조건을 끝까지 돌리지 못했거나 "
            f"함수 경계를 얻지 못했습니다(시간 초과·매치 상한 등). 그 파일의 판정은 '불확실'로 남았을 수 있습니다"
        )
    if result.engine_errors:
        gaps.append(f"  엔진 오류 {len(result.engine_errors)}건(어느 파일인지 모름): {result.engine_errors[0][:120]}")
    if result.skipped:
        names = ", ".join(rel(p, root) for p in result.skipped[:3])
        more = f" 외 {len(result.skipped) - 3}개" if len(result.skipped) > 3 else ""
        gaps.append(f"  건너뛴 파일 {len(result.skipped)}개({names}{more}) — {SKIPPED_REASONS}")
    note = st.dim("  이 도구는 법률 자문이 아닙니다. 검토가 필요한 지점을 고를 뿐입니다.")
    return "\n".join([body, *[st.soft(g) for g in gaps], note])
