"""2026-09-28 구조 점검의 1단계(판정 바로잡기)를 못 박는다.

점검에서 '문제 있는 코드를 문제없다'고 내게 만든 길을 찾았다. 여기 시험은 그 길이 다시 열리지 않게 한다.
- 근거 관문은 인용 전체가 실제 코드에 있어야 한다(지어낸 URL 이 통과하던 구멍).
- 판정자가 없거나 답하지 못하면 AI 가 필요했던 곳을 보고하고, 두 경우의 판정이 같다. 일부만 답해도 없을 때보다
  센 결론을 내지 않는다.
- AI 가 풀거나 뺀 판정은 결과에 남는다.
- .mts·.cts 는 엔진이 읽지 못하므로 검사하지 않은 파일로 알린다.
- 적용 조건과 대안의 id 가 같으면 팩을 읽을 때 멈춘다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from policypack.evaluate.engine import Target, evaluate
from policypack.evidence import is_grounded
from policypack.judge.base import Answer
from policypack.judge.fake import FakeJudge
from policypack.pack.loader import load_pack
from policypack.report.outcome import Outcome, UntestedReason
from policypack.static.backend import PredicateKey, StaticResult
from policypack.static.compile import compile_static
from policypack.static.semgrep_cli import SemgrepBackend

REPO = Path(__file__).resolve().parents[1]
KR = REPO / "policies" / "kr-core"
FIX = KR / "tests"


@pytest.fixture(scope="module")
def pack():
    return load_pack(KR)


def _run(pack, path: Path, judge=None):
    static = SemgrepBackend().run(compile_static(pack), [path])
    return evaluate(pack, [Target(path=path, lang="typescript")], static, judge=judge)


def _pipa(result):
    return [f for f in result.findings if f.policy == "kr.pipa.22-2"]


# ── 근거 관문 ──────────────────────────────────────────────────────────────


def test_gate_rejects_a_made_up_url_that_shares_a_prefix_with_real_code():
    """인용만 떼어 주석을 걷으면 `https:` 만 남아 코드의 "https://..." 에 맞춰 통과한다.
    인용 전체가 먼저 코드에 있어야 한다."""
    code = 'const API = "https://ganada.example.com/v1";\nawait send(API);\n'
    assert not is_grounded("https://made-up.example.org/opt-out", code)
    assert is_grounded("https://ganada.example.com/v1", code)


def test_required_accepts_a_code_line_with_a_trailing_comment_but_strict_does_not():
    code = "ensureMinorPolicy(user); // 만 14세 확인\n// TODO: (광고) 가나다몰 02-123-4567 붙이기\nsend(x);\n"
    assert is_grounded("ensureMinorPolicy(user); // 만 14세 확인", code)
    assert not is_grounded("ensureMinorPolicy(user); // 만 14세 확인", code, strict=True)
    assert not is_grounded("// TODO: (광고) 가나다몰 02-123-4567 붙이기", code)


# ── 판정자 없음 · 고장 ─────────────────────────────────────────────────────


class _FailingJudge:
    """늘 쓸 만한 답을 주지 못하는 판정자."""

    id = "failing"

    def __init__(self, failure: str) -> None:
        self.failure = failure

    def ask(self, q) -> Answer:
        return Answer(raw="?", failure=self.failure)  # type: ignore[arg-type]


def test_without_a_judge_the_ai_turn_is_reported_not_hidden(pack):
    """정적 대안이 못 알아보는 적법 구현(ai-guard.ts). 판정자가 없으면 경고는 남되, AI 차례였다는 것을 알린다."""
    res = _run(pack, FIX / "pipa-22-2" / "ai-guard.ts")
    [f] = _pipa(res)
    assert f.outcome is Outcome.NEEDS_REVIEW
    assert f.ai_pending == ["ai-guard"]
    assert f.untested_reasons == [UntestedReason.NO_JUDGE]
    assert res.ai_pending >= 1 and res.questions_asked == 0
    assert any("AI 필요(판정자 없음)" in line for line in f.trace)


@pytest.mark.parametrize(
    ("failure", "reason"),
    [("transport", UntestedReason.JUDGE_UNAVAILABLE), ("missing", UntestedReason.JUDGE_UNAVAILABLE)],
)
def test_a_broken_judge_gives_the_same_verdict_as_no_judge(pack, failure, reason):
    """예전에는 답하지 못한 AI 대안을 '모름'으로 넣어, 판정자가 고장 나면 없을 때보다 약한 결론(불확실)이 났다."""
    path = FIX / "pipa-22-2" / "ai-guard.ts"
    none = _pipa(_run(pack, path))
    broken = _pipa(_run(pack, path, judge=_FailingJudge(failure)))
    assert [f.outcome for f in broken] == [f.outcome for f in none] == [Outcome.NEEDS_REVIEW]
    assert broken[0].ai_pending == ["ai-guard"]
    assert broken[0].untested_reasons == [reason]


class _PartialJudge:
    """적용 질문과 `answers` 에 있는 조건에만 답하고, 나머지는 실패한다."""

    id = "partial"

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers

    def ask(self, q) -> Answer:
        if q.predicate == "applies-ai":
            return Answer(raw="예")
        if q.predicate in self.answers:
            return Answer(raw=self.answers[q.predicate])
        return Answer(raw="?", failure="timeout")


def _rule31(result):
    return [f for f in result.findings if f.policy == "kr.ai-basic-act.31"]


LABEL_TEXT = FIX / "ai-basic-act-31" / "label-text.tsx"


def test_a_partly_failed_judge_is_not_more_certain_than_no_judge(pack):
    """AI 대안 둘 중 하나만 '아니오'로 답하고 하나는 실패했다. 약한 대안을 버리면 확실한 '검토 필요'가
    나서, 판정자가 아예 없을 때(불확실)보다 센 결론이 났다. 받지 못한 답이 있으면 약한 대안은 '모름'이다."""
    none = _rule31(_run(pack, LABEL_TEXT))
    partial = _rule31(_run(pack, LABEL_TEXT, judge=_PartialJudge({"ai-label": "아니오"})))
    assert [f.outcome for f in partial] == [f.outcome for f in none] == [Outcome.NEEDS_REVIEW_UNCERTAIN]
    assert partial[0].ai_pending == ["ai-machine-mark"]
    assert partial[0].untested_reasons == [UntestedReason.TIMEOUT]
    every = _rule31(_run(pack, LABEL_TEXT, judge=_PartialJudge({"ai-label": "아니오", "ai-machine-mark": "아니오"})))
    assert [f.outcome for f in every] == [Outcome.NEEDS_REVIEW], "다 답했으면 약한 근거는 재확인된 것이다"


def test_weak_evidence_that_was_not_confirmed_shows_in_the_trace(pack):
    [f] = _rule31(_run(pack, LABEL_TEXT))
    assert "대안 label-text: 약한 근거 — AI 확인 전에는 풀지 않음 → unknown" in f.trace
    [g] = _rule31(_run(pack, LABEL_TEXT, judge=_PartialJudge({"ai-label": "아니오", "ai-machine-mark": "아니오"})))
    assert "대안 label-text: 약한 근거 — AI 답으로 대신함" in g.trace


def test_a_weak_alternative_without_an_ai_alternative_is_reported(pack):
    """AI 대안이 없는 규칙의 약한 대안은 어떤 판정자로도 확인되지 않는다. validate 가 알리고, 판정은 까닭을 단다."""
    from policypack.pack.loader import find_unconfirmable_weak

    assert find_unconfirmable_weak(pack) == []
    rules = []
    for pol in pack.policies:
        if pol.id == "kr.ai-basic-act.31":
            rule = pol.rules[0]
            rule = rule.model_copy(update={"compliant_if_any": [p for p in rule.compliant_if_any if not p.is_ai]})
            pol = pol.model_copy(update={"rules": [rule]})
        rules.append(pol)
    weak_only = pack.model_copy(update={"policies": rules})
    [w] = find_unconfirmable_weak(weak_only)
    assert "label-text" in w
    [f] = _rule31(_run(weak_only, LABEL_TEXT, judge=FakeJudge("예", echo_first_line=True)))
    assert f.outcome is Outcome.NEEDS_REVIEW_UNCERTAIN
    assert f.untested_reasons == [UntestedReason.WEAK_UNCONFIRMED] and f.ai_pending == []


def test_an_unparseable_answer_is_not_reported_as_an_unreachable_judge(pack):
    [f] = _pipa(_run(pack, FIX / "pipa-22-2" / "ai-guard.ts", judge=_FailingJudge("parse")))
    assert f.untested_reasons == [UntestedReason.JUDGE_UNPARSEABLE]


def test_pending_ai_is_counted_only_where_a_warning_remains(pack):
    """적용이 '모름'이면 적용 질문이 필요하다. 판정자가 없으면 그 단위는 'AI 필요'지만 강한 정적 대안이 이미
    풀었으니 답을 받았어도 결론이 같다. 경고로 남은 단위만 'AI 확인이 필요한 곳'으로 센다."""
    path = (FIX / "pipa-22-2" / "under14-branch.ts").resolve()
    static = SemgrepBackend().run(compile_static(pack), [path])
    key = PredicateKey("kr.pipa.22-2", "signup-without-guard", "applies-when", "birth-or-age")
    static.matches = [m for m in static.matches if m.key != key]
    static.predicate_timeouts[path] = [key]
    res = evaluate(pack, [Target(path=path, lang="typescript")], static)
    [u] = [u for u in res.units if u.policy.id == "kr.pipa.22-2"]
    assert u.pending == ["applies-ai"]
    assert _pipa(res) == [] and res.ai_pending == 0


def test_a_judge_that_answers_unknown_has_answered(pack):
    """판정자가 '모름'(?)이라고 답한 것은 실패가 아니다. '모름'으로 넣어 불확실로 남기고, 판정자를 부르지 못했다고
    적지 않는다. 실패로 다루자 스텁 unknown 이 판정자 없음과 같은 확실한 경고가 됐다(검토에서 실측)."""
    res = _run(pack, FIX / "pipa-22-2" / "ai-guard.ts", judge=FakeJudge("?"))
    [f] = _pipa(res)
    assert f.outcome is Outcome.NEEDS_REVIEW_UNCERTAIN
    assert f.untested_reasons == [] and f.ai_pending == []
    assert res.ai_answered >= 1


def test_a_clearance_on_a_line_with_a_trailing_comment_records_the_gate_class(pack, tmp_path):
    """AI 가 푼 경고는 인용과 관문이 본 분류를 남긴다. 관문이 받은 끝 주석 줄은 trailing-comment 로 적힌다."""
    from policypack.report import json_out

    line = "await gateway.enforceQuietHours(); // 야간 발송 차단"
    f = tmp_path / "blast.ts"
    f.write_text(
        "export async function blast(users) {\n"
        f"  {line}\n"
        '  for (const u of users) await sms.send(u.phone, "(광고) 가을 세일");\n}\n',
        encoding="utf-8",
    )
    static = SemgrepBackend().run(compile_static(pack), [f])
    res = evaluate(pack, [Target(path=f, lang="typescript")], static, judge=FakeJudge("예", evidence=line))
    assert not [x for x in res.findings if x.policy == "kr.network-act.50-3"]
    [c] = [c for c in json_out.build(res, root=tmp_path)["run"]["ai_cleared"] if c["policy"] == "kr.network-act.50-3"]
    [alt] = c["alternatives"]
    assert alt["id"] == "ai-night-guard" and alt["gate"] == "trailing-comment" and alt["cite"] == line


# ── AI 가 풀거나 뺀 판정의 기록 ─────────────────────────────────────────────


def test_a_warning_cleared_by_ai_is_recorded_with_its_citation(pack):
    res = _run(pack, FIX / "pipa-22-2" / "ai-guard.ts", judge=FakeJudge("예", echo_first_line=True))
    assert _pipa(res) == []
    [c] = [c for c in res.ai_cleared if c["policy"] == "kr.pipa.22-2"]
    [alt] = c["alternatives"]
    assert alt["id"] == "ai-guard" and alt["cite"] and alt["gate"] == "grounded"


def test_a_warning_cleared_by_static_evidence_is_not_counted_as_ai(pack):
    res = _run(pack, FIX / "pipa-22-2" / "under14-branch.ts", judge=FakeJudge("예", echo_first_line=True))
    assert not [c for c in res.ai_cleared if c["policy"] == "kr.pipa.22-2"]


def test_a_unit_dropped_by_the_applicability_question_is_recorded(pack):
    """엔진이 파일을 끝내지 못하면 적용이 '모름'이고, 적용 질문의 '아니오'는 인용 없이 단위를 뺀다."""
    path = (FIX / "pipa-22-2" / "violating.ts").resolve()
    static = StaticResult(incomplete={path})
    res = evaluate(pack, [Target(path=path, lang="typescript")], static, judge=FakeJudge("아니오"))
    assert _pipa(res) == []
    [d] = [d for d in res.ai_dismissed if d["policy"] == "kr.pipa.22-2"]
    assert d["answer"] == "아니오" and d["question"]


# ── 확장자 ─────────────────────────────────────────────────────────────────


def test_mts_and_cts_are_reported_as_unscanned(tmp_path):
    """고정한 Semgrep 은 .mts·.cts 를 TypeScript 로 읽지 않고 오류도 남기지 않는다. 검사한 것으로 세면 안 된다."""
    from policypack.discover import discover

    (tmp_path / "a.ts").write_text("export const a = 1;\n", encoding="utf-8")
    (tmp_path / "b.mts").write_text("export const b = 1;\n", encoding="utf-8")
    (tmp_path / "c.cts").write_text("export const c = 1;\n", encoding="utf-8")
    found = discover([tmp_path], ["javascript", "typescript"], use_git=False)
    assert [p.name for p in found.files] == ["a.ts"]
    assert sorted(p.name for p in found.skipped_engine) == ["b.mts", "c.cts"]
    named = discover([tmp_path / "b.mts"], ["typescript"], use_git=False)
    assert named.files == [] and [p.name for p in named.skipped_engine] == ["b.mts"]


def test_upper_case_extensions_are_reported_as_unscanned(tmp_path):
    """Semgrep 은 Mail.TS·a.Ts 를, 이름을 대도 오류 없이 건너뛴다(검토에서 실측). 이름을 댄 파일은 확장자를
    묻지 않고 엔진에 넘긴다(.sh 등). 같은 파일을 여러 경로로 만나도 건너뛴 파일은 한 번만 세고, 다른 경로로
    검사한 파일은 건너뛴 파일로 적지 않는다."""
    from policypack.discover import discover

    for name in ("a.ts", "Mail.TS", "b.Ts", "deploy.sh", "c.MTS", "app.min.js"):
        (tmp_path / name).write_text("export const a = 1;\n", encoding="utf-8")
    found = discover([tmp_path], ["javascript", "typescript"], use_git=False)
    assert [p.name for p in found.files] == ["a.ts"]
    assert sorted(p.name for p in found.skipped_engine) == ["Mail.TS", "b.Ts", "c.MTS"]
    named = discover([tmp_path / "deploy.sh", tmp_path / "Mail.TS"], ["typescript"], use_git=False)
    assert [p.name for p in named.files] == ["deploy.sh"] and [p.name for p in named.skipped_engine] == ["Mail.TS"]
    twice = discover([tmp_path, tmp_path, tmp_path / "Mail.TS", tmp_path / "app.min.js"], ["typescript"], use_git=False)
    assert sorted(p.name for p in twice.skipped_engine) == ["Mail.TS", "b.Ts", "c.MTS"]
    assert sorted(p.name for p in twice.skipped_files()) == ["Mail.TS", "b.Ts", "c.MTS"]


def test_a_fixture_the_engine_cannot_read_is_rejected(tmp_path):
    from policypack.errors import PackError
    from policypack.packtest import load_test_file

    (tmp_path / "v.mts").write_text("export const a = 1;\n", encoding="utf-8")
    suite = tmp_path / "t.test.yaml"
    suite.write_text(
        "apiVersion: policypack/test-0.1\nrule: kr.pipa.22-2/signup-without-guard\n"
        "cases:\n  - file: v.mts\n    expect: needs-review\n",
        encoding="utf-8",
    )
    with pytest.raises(PackError, match="엔진이 읽지 못하는"):
        load_test_file(suite, load_pack(KR), tmp_path)


def test_every_language_glob_is_really_read_by_the_pinned_engine(tmp_path):
    """LANGUAGE_GLOBS 의 확장자마다 언어 규칙이 실제로 매치해야 한다. 안 읽는 확장자를 넣으면 조용히 '거짓'이 된다."""
    from policypack.static.compile import LANGUAGE_GLOBS

    files = []
    for lang in ("javascript", "typescript"):
        for glob in LANGUAGE_GLOBS[lang]:
            f = tmp_path / f"probe{glob.lstrip('*')}"
            f.write_text("markerCall(1);\n", encoding="utf-8")
            files.append(f)
    cfg = {
        "rules": [
            {
                "id": "probe",
                "languages": ["javascript", "typescript"],
                "severity": "INFO",
                "message": "x",
                "pattern": "markerCall(...)",
                "metadata": {"policypack": {"policy": "p", "rule": "r", "group": "applies-when", "predicate": "q"}},
            }
        ]
    }
    static = SemgrepBackend().run(cfg, files)
    matched = {m.path.resolve() for m in static.matches}
    assert matched == {f.resolve() for f in files}, sorted(f.name for f in files if f.resolve() not in matched)


# ── 팩 문법 ────────────────────────────────────────────────────────────────


def test_same_id_in_applies_when_and_alternatives_fails_at_load(pack):
    from pydantic import ValidationError

    from policypack.model import Rule

    rule = next(r for _, r in pack.iter_rules() if r.id == "signup-without-guard")
    clash = rule.compliant_if_any[0].model_copy(update={"id": rule.applies_when[0].id})
    data = rule.model_dump(by_alias=True, exclude_none=True)
    data["compliant-if-any"][0]["id"] = clash.id
    with pytest.raises(ValidationError, match="적용 조건과 대안의 id 가 같습니다"):
        Rule.model_validate(data)


# ── 출력 ───────────────────────────────────────────────────────────────────


def test_json_and_text_report_the_ai_turn(tmp_path, monkeypatch, capsys):
    from policypack.cli import main

    src = (FIX / "pipa-22-2" / "ai-guard.ts").read_text(encoding="utf-8")
    (tmp_path / "a.ts").write_text(src, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    main(["scan", "a.ts", "--output-format", "json"])
    out = json.loads(capsys.readouterr().out)
    assert out["run"]["ai_pending"] == 1 and out["run"]["ai_cleared"] == [] and out["run"]["ai_dismissed"] == []
    [f] = [f for f in out["findings"] if f["policy"] == "kr.pipa.22-2"]
    assert f["ai_pending"] == ["ai-guard"] and f["untested_reasons"] == ["no-judge"]
    main(["scan", "a.ts", "--no-color"])
    text = capsys.readouterr().out
    assert "AI 확인 필요  ai-guard" in text and "AI 확인이 필요한 곳 1건" in text
