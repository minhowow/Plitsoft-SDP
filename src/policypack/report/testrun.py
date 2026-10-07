"""`policypack test` 의 출력."""

from __future__ import annotations

import json
from pathlib import Path

from policypack import __version__
from policypack.packtest import CLEAR, TestRun, matches
from policypack.report.json_out import SCHEMA_VERSION
from policypack.report.paths import rel
from policypack.report.text import Style, use_color

LABEL = {
    "compliant": "충족 근거 발견",
    "needs-review": "검토 필요",
    "needs-review-uncertain": "검토 필요(불확실)",
    "not-applicable": "해당 없음",
    CLEAR: "경고 없음",
}


def render(run: TestRun, root, explain: bool = False, color: bool | None = None, pack_path=None) -> str:
    st = Style(use_color() if color is None else color)
    out: list[str] = []
    by_rule: dict[str, list] = {}
    for r in run.rows:
        # 적은 규칙은 늘 보이고, 적지 않은 규칙은 실패했을 때만 보인다
        if r.declared or not r.passed:
            by_rule.setdefault(r.ref, []).append(r)
    width = max((len(r.fixture.id) for r in run.rows), default=20)
    for ref, rows in by_rule.items():
        out.append(st.bold(ref))
        for r in rows:
            if r.passed:
                out.append(f"  {st.ok('통과')}  {r.fixture.id:<{width}}  {LABEL[r.actual]}")
                if explain:
                    out.extend(st.dim(f"        {t}") for t in r.trace)
                continue
            if r.declared:
                why = f"기대 {LABEL[r.expected]} · 실제 {LABEL[r.actual]}"
            else:
                why = f"적지 않은 규칙이 걸렸습니다 · 실제 {LABEL[r.actual]}"
            if r.unanswered and matches(r.expected, r.actual):
                why = f"{LABEL[r.actual]} · 답이 적히지 않은 AI 질문이 있습니다"
            out.append(f"  {st.warn('실패')}  {r.fixture.id:<{width}}  {why}")
            if r.fixture.note:
                out.append(f"        {r.fixture.note}")
            for m in r.unanswered:
                out.append(f"        답 없는 AI 질문: {m.rsplit('/', 1)[-1]}")
            out.extend(st.dim(f"        {t}") for t in r.trace)
        out.append("")

    out.append(st.bold("커버리지"))
    for c in run.coverage:
        alts = c.sole
        testable = [a for a in alts if a not in c.not_testable]
        ok = sum(1 for a in testable if alts[a])
        decoyed = sum(1 for fxs in c.decoys.values() if fxs)
        decoy = f" · 음성 {decoyed}/{len(c.decoys)}" if c.decoys else ""
        out.append(f"  {c.rule}  위반 {len(c.raising)} · 대안 {ok}/{len(testable)} 단독 해제{decoy}")
        for g in c.gaps:
            out.append(st.soft(f"    - {g}"))
        if c.not_testable:
            out.append(st.dim(f"    · 혼자서는 풀 수 없는 대안(AI 확인이 있어야 푼다): {', '.join(c.not_testable)}"))
    if run.unused_stubs:
        names = ", ".join(f"{k[0]}:{k[3]}" for k in run.unused_stubs)
        out.append(st.dim(f"  쓰이지 않은 AI 답 {len(run.unused_stubs)}개: {names}"))

    declared = [r for r in run.rows if r.declared]
    passed = sum(1 for r in declared if r.passed)
    asked = run.stats["questions_asked"]
    parts = [f"픽스처 {len(run.fixtures)}", f"기대 {len(declared)}", f"통과 {passed}", f"실패 {len(run.failed)}"]
    parts.append(f"커버리지 빈틈 {run.gaps}")
    engine = run.engine or "엔진"
    tail = f"판정자 AI 답 스텁 · {engine} {run.engine_runs}회 {run.static_seconds:.1f}초 · AI 질문 {asked}회"
    head = st.ok("요약") if not run.failed else st.warn("요약")
    out.append("")
    if run.engine_errors:
        out.append(
            st.warn(
                f"엔진 오류 {len(run.engine_errors)}건(어느 파일인지 모름): {run.engine_errors[0][:120]} — "
                f"그 실행의 픽스처는 모든 정적 조건이 '모름'이 됐습니다. 실패의 원인이 규칙이 아닐 수 있습니다."
            )
        )
    if pack_path is not None:
        # 실행 위치 밖의 팩(설치본 등)을 ../../.. 로 적으면 읽기 어렵다. 그때는 절대 경로다
        inside = root is None or pack_path.resolve().is_relative_to(Path(root).resolve())
        out.append(st.dim(f"팩  {rel(pack_path, root) if inside else pack_path.resolve()}"))
    out.append(f"{head}  {' · '.join(parts)}  ({tail}, 모델 호출 0회)")
    return "\n".join(out)


def build(run: TestRun, root, pack_id: str, pack_digest: str) -> dict:
    declared = [r for r in run.rows if r.declared]
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "policypack", "version": __version__},
        "run": {
            "command": "test",
            "pack": pack_id,
            "pack_digest": pack_digest,
            "engine": {"name": run.engine.partition(" ")[0], "version": run.engine.partition(" ")[2] or None}
            if run.engine
            else None,
            "engine_runs": run.engine_runs,
            "engine_errors": list(run.engine_errors),
            "static_seconds": round(run.static_seconds, 3),
            **run.stats,
        },
        "results": [
            {
                "fixture": r.fixture.id,
                "file": rel(r.fixture.path, root),
                "rule": r.ref,
                "declared": r.declared,
                "expected": r.expected,
                "actual": r.actual,
                "passed": r.passed,
                "unanswered": r.unanswered,
                "decision_path": r.trace,
            }
            for r in run.rows
        ],
        "coverage": [
            {
                "rule": c.rule,
                "raising": c.raising,
                "sole_clearing": c.sole,
                "decoys": c.decoys,
                "never_true": c.never_true,
                "not_testable_alone": c.not_testable,
                "gaps": c.gaps,
            }
            for c in run.coverage
        ],
        "unused_stubs": [":".join((k[0], "/".join(k[1:]))) for k in run.unused_stubs],
        "summary": {
            "fixtures": len(run.fixtures),
            "expectations": len(declared),
            "passed": sum(1 for r in declared if r.passed),
            "failed": len(run.failed),
            "gaps": run.gaps,
        },
    }


def dumps(*args, **kwargs) -> str:
    return json.dumps(build(*args, **kwargs), ensure_ascii=False, indent=2)
