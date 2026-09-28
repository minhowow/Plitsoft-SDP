"""`policypack test` — 정책 작성자의 단위 테스트가 믿을 만한가.

이 명령이 거짓으로 통과하면, 새 정책이 대안 하나를 조용히 못 알아보는 채로 들어온다.
그래서 러너 자체를 시험한다: 스텁이 근거 관문을 우회하지 못하는지, 답 없는 질문이
실패인지, 적지 않은 규칙의 경고를 잡는지, 음성 픽스처(decoy-for)를 요구하는지.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from policypack.cli import main
from policypack.model import Strength
from policypack.pack.loader import load_pack, pack_digest

REPO = Path(__file__).resolve().parents[1]
KR_CORE = REPO / "policies" / "kr-core"
DATA = REPO / "tests" / "data" / "packtest"
RULE = "kr.pipa.22-2/signup-without-guard"


@pytest.fixture(autouse=True)
def _in_repo(monkeypatch):
    monkeypatch.chdir(REPO)


def run_json(*args) -> tuple[int, dict]:
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(["test", *args, "--output-format", "json"])
    return code, (json.loads(buf.getvalue()) if buf.getvalue().strip() else {})


def write_suite(tmp_path: Path, cases: str, rule: str = RULE) -> Path:
    """tests/data 의 픽스처를 쓰는 테스트 파일 하나."""
    for f in DATA.iterdir():
        (tmp_path / f.name).write_bytes(f.read_bytes())
    p = tmp_path / "t.test.yaml"
    p.write_text(f"apiVersion: policypack/test-0.1\nrule: {rule}\ncases:\n{cases}", encoding="utf-8")
    return p


# ── 내장 팩 ─────────────────────────────────────────────────────────────────


def test_kr_core_fixtures_pass_strictly():
    """위반 모양 하나, 대안마다 그 대안 하나로 풀리는 픽스처 하나. 빈틈이 없어야 한다."""
    code, out = run_json("--strict")
    assert code == 0, [r for r in out["results"] if not r["passed"]]
    assert out["summary"]["failed"] == 0 and out["summary"]["gaps"] == 0
    assert out["run"]["missing"] == 0


def test_every_rule_has_a_violating_fixture_and_sole_clearers():
    """약한 대안은 AI 확인 없이 혼자 경고를 풀 수 없다. 그런 대안은 단독 해제를 요구하지 않는다.

    혼자 풀 수 있는 정적 대안에는 반대로 '비슷하지만 풀리면 안 되는' 음성 픽스처(decoy-for)를 요구한다."""
    _, out = run_json()
    pack = load_pack(KR_CORE)
    rules = {f"{p.id}/{r.id}": r for p, r in pack.iter_rules()}
    assert {c["rule"] for c in out["coverage"]} == set(rules)
    for c in out["coverage"]:
        assert c["raising"], c["rule"]
        for alt in rules[c["rule"]].compliant_if_any:
            if alt.id in c["not_testable_alone"]:
                continue
            assert c["sole_clearing"][alt.id], f"{c['rule']}: 대안 {alt.id} 를 혼자 푸는 픽스처가 없다"
            if not alt.is_ai:
                assert c["decoys"][alt.id], f"{c['rule']}: 정적 대안 {alt.id} 의 음성 픽스처가 없다"


def test_tests_directory_does_not_change_the_pack_digest(tmp_path):
    """픽스처를 더할 때마다 판정 지문이 바뀌면 baseline 이 깨진다."""
    import shutil

    copy = tmp_path / "kr-core"
    shutil.copytree(KR_CORE, copy, ignore=shutil.ignore_patterns("tests"))
    assert pack_digest(copy) == pack_digest(KR_CORE)


# ── 스텁은 근거 관문을 우회하지 못한다 ──────────────────────────────────────


def test_uncited_yes_cannot_clear(tmp_path):
    """방향성 신뢰. 인용 없는 '예'는 '모름'이 되어 경고가 남는다."""
    suite = write_suite(
        tmp_path, "  - file: ai-guard.ts\n    expect: needs-review-uncertain\n    ai: {ai-guard: yes}\n"
    )
    code, out = run_json(str(suite))
    assert code == 0, out["results"]


def test_citation_that_is_not_in_the_code_cannot_clear(tmp_path):
    suite = write_suite(
        tmp_path,
        "  - file: ai-guard.ts\n    expect: compliant\n"
        "    ai: {ai-guard: {answer: yes, cite: 'if (age < 14) throw new Error()'}}\n",
    )
    code, out = run_json(str(suite))
    assert code == 1
    row = next(r for r in out["results"] if r["rule"] == RULE)
    assert row["actual"] == "needs-review-uncertain"


def test_unanswered_question_fails_even_if_the_outcome_matches(tmp_path):
    """스텁이 없으면 답이 없다. 답 없는 AI 대안은 판정에 넣지 않아 정적 판정(검토 필요)이 남는다.
    우연히 기대와 맞아도 시험은 아무것도 보여 주지 못했으므로 실패다."""
    suite = write_suite(tmp_path, "  - file: violating.ts\n    expect: needs-review\n")
    code, out = run_json(str(suite))
    assert code == 1
    row = next(r for r in out["results"] if r["rule"] == RULE)
    assert row["actual"] == "needs-review" and row["unanswered"] == [f"{RULE}/ai-guard"]


def test_undeclared_rule_that_fires_is_a_failure(tmp_path):
    """semgrep --test 와 같다. 적지 않은 규칙이 걸리면 다른 정책의 오탐이다."""
    (tmp_path / "page.tsx").write_text(
        "export default function Signup() {\n  const aiTip = useAssistant();\n"
        '  return (<form><input name="birthDate" /><p>{aiTip}</p></form>);\n}\n',
        encoding="utf-8",
    )
    suite = write_suite(tmp_path, "  - file: page.tsx\n    expect: needs-review\n    ai: {ai-guard: no}\n")
    code, out = run_json(str(suite))
    assert code == 1
    failed = [r for r in out["results"] if not r["passed"]]
    assert [r["rule"] for r in failed] == ["kr.ai-basic-act.31/ai-output-without-label"]
    assert not failed[0]["declared"]


def test_same_file_twice_with_different_stubs(tmp_path):
    """반사실 픽스처. 같은 코드에 답만 바꿔 두 번 쓴다. 판정 단위가 경로로 합쳐지면 안 된다."""
    cite = 'if (isMinor(body.birthDate)) return res.status(403).json({ error: "MINOR" });'
    suite = write_suite(
        tmp_path,
        "  - file: ai-guard.ts\n    id: cited\n    expect: compliant\n"
        f"    ai: {{ai-guard: {{answer: yes, cite: '{cite}'}}}}\n"
        "  - file: ai-guard.ts\n    id: uncited\n    expect: needs-review-uncertain\n    ai: {ai-guard: yes}\n",
    )
    code, out = run_json(str(suite))
    assert code == 0, [r for r in out["results"] if not r["passed"]]


# ── 파일 문법 ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "cases,rule,msg",
    [
        ("  - file: violating.ts\n    expect: needs-review\n", "kr.nope/rule", "팩에 없는 규칙"),
        (
            "  - file: violating.ts\n    expect: needs-review\n    ai: {under14-branch: no}\n",
            RULE,
            "AI 조건이 아닙니다",
        ),
        ("  - file: violating.ts\n    expect: needs-review\n    ai: {ai-guard: {answer: no, cite: x}}\n", RULE, "cite"),
        ("  - file: missing.ts\n    expect: needs-review\n", RULE, "픽스처가 없습니다"),
        ("  - file: violating.ts\n    expect: maybe\n", RULE, "문법"),
        (
            "  - file: violating.ts\n    expect: needs-review\n  - file: violating.ts\n    expect: needs-review\n",
            RULE,
            "겹칩니다",
        ),
    ],
    ids=["unknown-rule", "stub-on-static", "cite-on-no", "missing-file", "bad-outcome", "duplicate-id"],
)
def test_bad_test_files_are_tool_errors(tmp_path, capsys, cases, rule, msg):
    suite = write_suite(tmp_path, cases, rule=rule)
    assert main(["test", str(suite)]) == 2
    assert msg in capsys.readouterr().err


def test_yes_and_no_are_strings_not_booleans(tmp_path):
    """YAML 1.1 이면 no 가 False 가 된다. ruamel(1.2)로 읽는다."""
    from policypack.packtest import PolicyTestFile, _read_yaml

    p = write_suite(tmp_path, "  - file: violating.ts\n    expect: needs-review\n    ai: {ai-guard: no}\n")
    tf = PolicyTestFile.model_validate(_read_yaml(p))
    assert tf.cases[0].ai["ai-guard"].answer.value == "no"


# ── 커버리지 규칙은 planner 와 같다 ─────────────────────────────────────────


def test_can_clear_alone_follows_the_planner():
    from policypack.packtest import can_clear_alone

    pack = load_pack(KR_CORE)
    for _, rule in pack.iter_rules():
        for p in rule.compliant_if_any:
            expected = True if p.is_ai else p.strength is not Strength.WEAK
            assert can_clear_alone(rule, p) is expected, p.id


def test_worst_outcome_wins_when_a_rule_yields_several_findings():
    """scope: anchor 에서는 한 파일에 판정이 여럿이다. 하나라도 경고면 경고다."""
    from policypack.evaluate.engine import EvalResult
    from policypack.packtest import Fixture, outcome_table
    from policypack.report.outcome import Finding, Outcome

    pack = load_pack(KR_CORE)
    fx = Fixture(id="f", path=Path("f.ts"), lang="typescript", expects={})
    res = EvalResult()
    for o in (Outcome.NEEDS_REVIEW, Outcome.COMPLIANT, Outcome.NEEDS_REVIEW_UNCERTAIN):
        res.findings.append(
            Finding(policy="kr.pipa.22-2", rule="signup-without-guard", outcome=o, file="f.ts", case="f")
        )
    assert outcome_table(pack, [fx], res)[("f", RULE)] == "needs-review"


# ── 검토 반영 ───────────────────────────────────────────────────────────────


def _copy_pack(tmp_path) -> Path:
    import shutil

    dst = tmp_path / "mypack"
    shutil.copytree(KR_CORE, dst)
    return dst


def test_tests_dir_is_run_against_its_own_pack(tmp_path):
    """<팩>/tests 를 주면 그 팩으로 시험한다. 내장 kr-core 로 돌리면 엉뚱한 결과가 나왔다."""
    pack = _copy_pack(tmp_path)
    (pack / "pack.yaml").write_text(
        (pack / "pack.yaml").read_text(encoding="utf-8").replace("title: 국내 법·정책 검토 팩", "title: 복사본"),
        encoding="utf-8",
    )
    for arg in (pack / "tests", pack / "tests" / "pipa-22-2.test.yaml"):
        code, out = run_json(str(arg))
        assert code == 0 and out["run"]["pack_digest"] == pack_digest(pack), arg


def test_config_as_file_or_directory_is_the_same_pack():
    code, _ = run_json("policies/kr-core", "--config", "policies/kr-core/pack.yaml")
    assert code == 0


def test_qualified_stub_keys(tmp_path):
    """applies-ai 처럼 여러 규칙이 같은 이름을 쓰면 '정책/규칙/조건' 꼴로 적는다."""
    suite = write_suite(
        tmp_path,
        "  - file: violating.ts\n    expect: needs-review\n    ai: {kr.pipa.22-2/signup-without-guard/ai-guard: no}\n",
    )
    code, out = run_json(str(suite))
    assert code == 0, [r for r in out["results"] if not r["passed"]]
    bad = write_suite(
        tmp_path, "  - file: violating.ts\n    expect: needs-review\n    ai: {kr.pipa.22-2/nope/ai-guard: no}\n"
    )
    assert main(["test", str(bad)]) == 2


def test_strict_on_one_file_counts_only_its_rules():
    """테스트 파일 하나만 돌릴 때 다른 정책의 빈틈으로 실패하면 안 된다."""
    code, out = run_json("policies/kr-core/tests/pipa-22-2.test.yaml", "--strict")
    assert code == 0 and [c["rule"] for c in out["coverage"]] == [RULE]


def test_yml_extension_is_refused_not_skipped(tmp_path, capsys):
    suite = write_suite(tmp_path, "  - file: violating.ts\n    expect: needs-review\n    ai: {ai-guard: no}\n")
    suite.rename(tmp_path / "t.test.yml")
    assert main(["test", str(tmp_path)]) == 2
    assert ".test.yaml" in capsys.readouterr().err


def test_can_clear_alone_agrees_with_the_engine_without_ai_alternatives():
    """AI 대안이 없는 규칙의 약한 대안: 재확인할 판정자가 없으니 혼자 풀 수 없다(엔진과 같다)."""
    from policypack.model import Rule
    from policypack.packtest import can_clear_alone

    rule = Rule.model_validate(
        {
            "id": "r",
            "applies-when": [{"id": "a", "static": {"pattern": "f()"}}],
            "compliant-if-any": [
                {"id": "strong", "static": {"pattern": "g()"}},
                {"id": "weak", "strength": "weak", "static": {"pattern": "h()"}},
            ],
        }
    )
    assert can_clear_alone(rule, rule.compliant_if_any[0]) is True
    assert can_clear_alone(rule, rule.compliant_if_any[1]) is False


# ── 음성 픽스처(decoy-for) ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "cases,msg",
    [
        ("  - file: violating.ts\n    expect: needs-review\n    decoy-for: [ai-guard]\n", "정적 대안이 아닙니다"),
        ("  - file: violating.ts\n    expect: compliant\n    decoy-for: [under14-branch]\n", "기대가 경고가 아닙니다"),
    ],
    ids=["decoy-for-ai-alternative", "decoy-expected-clear"],
)
def test_bad_decoys_are_tool_errors(tmp_path, capsys, cases, msg):
    assert main(["test", str(write_suite(tmp_path, cases))]) == 2
    assert msg in capsys.readouterr().err


def test_strict_requires_a_decoy_for_every_static_clearer(tmp_path):
    """혼자 풀 수 있는 정적 대안(under14-branch)에 음성 픽스처가 없으면 --strict 가 빈틈으로 센다."""
    suite = write_suite(tmp_path, "  - file: violating.ts\n    expect: needs-review\n    ai: {ai-guard: no}\n")
    code, out = run_json(str(suite), "--strict")
    assert code == 1
    [cov] = out["coverage"]
    assert cov["decoys"] == {"under14-branch": []}
    assert any("under14-branch" in g and "decoy-for" in g for g in cov["gaps"])
    decoy = write_suite(
        tmp_path,
        "  - file: violating.ts\n    expect: needs-review\n    ai: {ai-guard: no}\n    decoy-for: [under14-branch]\n",
    )
    _, out = run_json(str(decoy), "--strict")
    assert out["coverage"][0]["decoys"] == {"under14-branch": ["violating.ts"]}
