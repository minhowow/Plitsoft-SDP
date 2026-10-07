"""scan 명령의 제품 표면.

종료 코드와 SARIF 는 CI 가 읽는 계약이다. 사람이 보는 출력보다 깨지기 쉽고,
깨져도 조용하다. 그래서 테스트로 고정한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from policypack.cli import main
from policypack.discover import discover, language_of

REPO = Path(__file__).resolve().parents[1]
FIX = "policies/kr-core/tests"
VIOLATING = f"{FIX}/pipa-22-2/violating.ts"
COMPLIANT = f"{FIX}/pipa-22-2/under14-branch.ts"


@pytest.fixture(autouse=True)
def _in_repo(monkeypatch):
    monkeypatch.chdir(REPO)


def run(*args) -> int:
    return main(["scan", *args])


# ── 종료 코드 ───────────────────────────────────────────────────────────────


def test_exit_1_when_something_needs_review(capsys):
    assert run(VIOLATING, "--no-color", "--output-format", "concise") == 1
    assert "검토 필요" in capsys.readouterr().out


def test_exit_0_when_nothing_needs_review(capsys):
    assert run(COMPLIANT, "--no-color", "--output-format", "concise") == 0


def test_exit_zero_flag_overrides(capsys):
    assert run(VIOLATING, "--exit-zero", "--no-color", "--output-format", "concise") == 0


def test_fail_on_never(capsys):
    assert run(VIOLATING, "--fail-on", "never", "--no-color", "--output-format", "concise") == 0


def test_exit_2_on_tool_error(capsys):
    """도구 오류(2)와 검토 필요(1)를 가르는 것이 종료 코드 규약의 핵심이다.

    CI 에서 전자는 파이프라인이 멈출 일이고 후자는 사람이 볼 일이다.
    """
    assert run(VIOLATING, "--config", "/없는/경로") == 2
    assert "오류" in capsys.readouterr().err


def test_exit_2_on_unknown_judge(capsys):
    assert run(VIOLATING, "--judge", "openai:gpt") == 2
    err = capsys.readouterr().err
    assert "모르는 판정자" in err
    assert "claude-cli" in err and "anthropic" in err, "쓸 수 있는 것을 알려 줘야 한다"


def test_internal_errors_exit_2_not_1(monkeypatch, capsys):
    """처리하지 못한 예외로 파이썬이 1로 끝나면 CI 는 '검토 필요'로 읽는다."""
    import policypack.cli as cli

    monkeypatch.setitem(cli.COMMANDS, "scan", lambda args: 1 / 0)
    assert cli.main(["scan"]) == 2
    assert "내부 오류" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["scan", ".", "--mode", "lazy"],
        ["scan", ".", "--gate", "v1"],
        ["scan", ".", "--context", "callees"],
        ["scan", ".", "--no-security"],
        ["scan", ".", "--rules", "rules.yaml"],
        ["scan", ".", "--record", "rec.jsonl"],
        ["test", "--judge", "stub"],
        ["test", "--judge-id", "claude:haiku"],
        ["test", "--set", "dev"],
        ["test", "--labels", "original"],
        ["test", "--rep", "1"],
        ["test", "--mode", "lazy"],
        ["test", "--gate", "v1"],
        ["legal"],
    ],
    ids=lambda a: " ".join(a[:1] + a[2:3] if a[0] == "scan" else a[:2]),
)
def test_research_options_are_gone(argv):
    """판정 방식을 바꾸는 연구용 옵션은 지웠다. 남아 있으면 같은 팩의 뜻이 옵션에 따라 달라진다."""
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code == 2


def test_recordings_are_not_a_judge(capsys):
    """녹화 재생 판정자(cache:)는 지웠다. 모르는 판정자로 알린다."""
    assert run(VIOLATING, "--judge", "cache:somewhere") == 2
    assert "모르는 판정자" in capsys.readouterr().err


# ── SARIF ───────────────────────────────────────────────────────────────────


@pytest.fixture
def sarif(capsys):
    run(f"{FIX}/pipa-22-2", "--output-format", "sarif")
    return json.loads(capsys.readouterr().out)


def test_sarif_shape(sarif):
    assert sarif["version"] == "2.1.0"
    assert sarif["$schema"].endswith("sarif-2.1.0.json")
    run_ = sarif["runs"][0]
    assert run_["tool"]["driver"]["name"] == "policypack"
    assert run_["results"], "판정이 하나는 있어야 한다"


def test_sarif_carries_the_statute_text(sarif):
    """근거 조문이 개발자에게 닿는 자리다.

    GitHub·GitLab 코드 스캐닝이 help.markdown 을 그대로 보여 준다. 도구를 떠나지
    않고 조문을 읽을 수 있어야 한다.
    """
    rules = {r["id"]: r for r in sarif["runs"][0]["tool"]["driver"]["rules"]}
    child = rules["kr.pipa.22-2/signup-without-guard"]
    md = child["help"]["markdown"]
    assert "제22조의2" in md
    assert "법정대리인의 동의" in md, "조문 원문이 실려야 한다"
    assert "받은 판본의 시행일 2026-09-11" in md
    assert "법률 자문이 아닙니다" in md
    assert child["helpUri"].startswith("https://www.law.go.kr")


def test_sarif_marks_the_pack_authors_words_as_not_the_statute(sarif):
    """help.markdown 에는 팩 작성자의 글과 조문 원문이 함께 실린다. 작성자의 글이 법의 말로 읽히면 안 된다."""
    from policypack.pack.loader import load_pack

    rules = {r["id"]: r for r in sarif["runs"][0]["tool"]["driver"]["rules"]}
    md = rules["kr.pipa.22-2/signup-without-guard"]["help"]["markdown"]
    policy = next(p for p in load_pack(REPO / "policies/kr-core").policies if p.id == "kr.pipa.22-2")
    note = md.index("### 팩 작성자의 설명 (법 원문이 아닙니다)")
    statute = md.index("### 개인정보 보호법 제22조의2")
    assert note < md.index(policy.rationale.motivation.strip()) < statute


def test_sarif_tags_carry_the_law(sarif):
    tags = sarif["runs"][0]["tool"]["driver"]["rules"][0]["properties"]["tags"]
    assert any(t.startswith("law:") for t in tags)


def test_sarif_tags_are_unique(capsys):
    """한 조의 두 항을 고정한 정책(kr.network-act.50-4)에서 같은 태그가 두 번 나갔다. tags 는 중복이 없어야 한다."""
    run(f"{FIX}/network-act-50-4", "--output-format", "sarif")
    rules = json.loads(capsys.readouterr().out)["runs"][0]["tool"]["driver"]["rules"]
    assert rules
    for rule in rules:
        tags = rule["properties"]["tags"]
        assert len(tags) == len(set(tags)), rule["id"]


def test_sarif_results_point_at_a_line(sarif):
    for res in sarif["runs"][0]["results"]:
        region = res["locations"][0]["physicalLocation"]["region"]
        assert region["startLine"] >= 1
        assert res["level"] in ("warning", "note")
        assert res["partialFingerprints"]


def test_sarif_records_how_it_was_run(sarif):
    """어떤 팩으로, 어떤 판정자로 나온 결과인지 남는다."""
    props = sarif["runs"][0]["invocations"][0]["properties"]
    assert props["packDigest"] and props["judge"] == "none"


# ── 지문 ────────────────────────────────────────────────────────────────────


def test_fingerprint_survives_an_unrelated_line_above(tmp_path):
    """위에 줄 하나 넣었다고 baseline 이 깨지면 안 된다."""
    from policypack.report.fingerprint import fingerprint
    from policypack.report.outcome import Finding, Outcome

    src = (REPO / VIOLATING).read_text(encoding="utf-8")
    a = tmp_path / "a.ts"
    a.write_text(src, encoding="utf-8")
    b = tmp_path / "a.ts"  # 같은 경로, 위에 줄 하나 추가
    finding_a = Finding(policy="p", rule="r", outcome=Outcome.NEEDS_REVIEW, file=str(a), line=3)
    fp_a = fingerprint(finding_a, "d")

    b.write_text("// 주석 한 줄 추가\n" + src, encoding="utf-8")
    finding_b = Finding(policy="p", rule="r", outcome=Outcome.NEEDS_REVIEW, file=str(b), line=4)
    assert fingerprint(finding_b, "d") == fp_a


def test_fingerprint_changes_when_the_pack_changes(tmp_path):
    from policypack.report.fingerprint import fingerprint
    from policypack.report.outcome import Finding, Outcome

    f = Finding(policy="p", rule="r", outcome=Outcome.NEEDS_REVIEW, file=str(REPO / VIOLATING), line=None)
    assert fingerprint(f, "digest-a") != fingerprint(f, "digest-b")


# ── 대상 고르기 ─────────────────────────────────────────────────────────────


def test_discover_skips_dependency_directories(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text("const a = 1;\n", encoding="utf-8")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "b.js").write_text("const b = 2;\n", encoding="utf-8")
    found = discover([tmp_path], ["javascript", "typescript"], use_git=False)
    names = {f.name for f in found.files}
    assert names == {"a.ts"}


def test_discover_does_not_skip_a_directory_named_test(tmp_path):
    """semgrep 에 디렉터리를 넘기면 test/ 를 통째로 건너뛴다. 우리는 그러면 안 된다.

    법 검토 도구가 사용자의 test 디렉터리를 말없이 건너뛰면 쓸모가 없다.
    """
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "a.ts").write_text("const signup = 1;\n", encoding="utf-8")
    found = discover([tmp_path], ["javascript", "typescript"], use_git=False)
    assert [f.name for f in found.files] == ["a.ts"]


def test_discover_skips_minified_files_but_counts_them(tmp_path):
    """축소된 파일은 검토도 수정도 할 수 없다. 대신 몇 개를 뺐는지는 남긴다.

    공개 저장소의 dat.gui.min.js·jquery-3.2.1.min.js 같은 번들은 1MB 미만이라 크기로는 걸리지 않는다.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text("const a = 1;\n", encoding="utf-8")
    (tmp_path / "src" / "dat.gui.min.js").write_text("var d=1,e=2;\n", encoding="utf-8")
    (tmp_path / "src" / "app.bundle.js").write_text("var f=3;\n", encoding="utf-8")
    # 이름에 min 이 들어가도 축소본이 아니면 검사한다
    (tmp_path / "src" / "minify.ts").write_text("const m = 1;\n", encoding="utf-8")

    found = discover([tmp_path], ["javascript", "typescript"], use_git=False)
    assert {f.name for f in found.files} == {"a.ts", "minify.ts"}
    assert {f.name for f in found.skipped_generated} == {"dat.gui.min.js", "app.bundle.js"}


def test_discover_skips_yarn_pnp_artifacts(tmp_path):
    """Yarn Berry 의 PnP 해석기와 .yarn/ 은 생성물이다. 검토할 수도 고칠 수도 없다."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text("const a = 1;\n", encoding="utf-8")
    (tmp_path / ".pnp.cjs").write_text("module.exports = {};\n", encoding="utf-8")
    (tmp_path / ".pnp.loader.mjs").write_text("export {};\n", encoding="utf-8")
    (tmp_path / ".yarn" / "sdks").mkdir(parents=True)
    (tmp_path / ".yarn" / "sdks" / "tsserver.js").write_text("x();\n", encoding="utf-8")
    found = discover([tmp_path], ["javascript", "typescript"], use_git=False)
    assert {f.name for f in found.files} == {"a.ts"}
    assert {f.name for f in found.skipped_generated} == {".pnp.cjs", ".pnp.loader.mjs"}


def test_a_named_minified_file_is_still_scanned(tmp_path):
    """사용자가 직접 이름을 대면 거르지 않는다. 다른 제외 규칙과 같다."""
    f = tmp_path / "vendor.min.js"
    f.write_text("var a=1;\n", encoding="utf-8")
    assert discover([f], ["javascript"], use_git=False).files == [f]


def test_named_file_is_taken_regardless_of_extension(tmp_path):
    """사용자가 직접 지정한 파일은 거르지 않는다."""
    odd = tmp_path / "script.mjs"
    odd.write_text("const a = 1;\n", encoding="utf-8")
    assert discover([odd], ["javascript"], use_git=False).files == [odd]


def test_defaults_fall_back_to_the_bundled_copy(tmp_path, monkeypatch):
    """pre-commit 훅은 사용자 저장소에서 돈다. 거기에는 policies/ 가 없다."""
    import policypack.defaults as d

    bundled = tmp_path / "_bundled"
    (bundled / "policies" / "kr-core").mkdir(parents=True)
    monkeypatch.setattr(d, "_REPO", tmp_path / "not-a-checkout")
    monkeypatch.setattr(d, "_BUNDLED", bundled)
    monkeypatch.delenv("POLICYPACK_PACK", raising=False)
    assert d.default_pack() == bundled / "policies" / "kr-core"


def test_environment_overrides_defaults(tmp_path, monkeypatch):
    import policypack.defaults as d

    monkeypatch.setenv("POLICYPACK_PACK", str(tmp_path / "mine"))
    assert d.default_pack() == tmp_path / "mine"


def test_scan_works_from_another_directory(tmp_path, monkeypatch, capsys):
    """사용자 저장소에서 돌리는 상황. 현재 폴더에 policies/ 가 없다."""
    (tmp_path / "app.ts").write_text((REPO / VIOLATING).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    code = main(["scan", "app.ts", "--no-color", "--output-format", "concise"])
    out = capsys.readouterr()
    assert code == 1, out.err
    assert "만 14세" in out.out


def test_file_names_that_look_like_options_stay_files(tmp_path, monkeypatch, capsys):
    """semgrep 에 대상을 `--` 없이 넘겨 '-' 로 시작하는 이름이 옵션이 됐다. `--json-output=index.ts` 라는 파일이
    있으면 index.ts 를 결과 JSON 으로 덮어썼고, `-signup.ts` 하나로 검사 전체가 실패했다(실측)."""
    (tmp_path / "index.ts").write_text("export const keep = 1;\n", encoding="utf-8")
    (tmp_path / "--json-output=index.ts").write_text("export {};\n", encoding="utf-8")
    (tmp_path / "-signup.ts").write_text((REPO / VIOLATING).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert run("--output-format", "concise", "--no-color") == 1
    assert (tmp_path / "index.ts").read_text(encoding="utf-8") == "export const keep = 1;\n"
    assert "-signup.ts" in capsys.readouterr().out


def test_a_pack_file_with_another_name_is_the_pack_that_runs(tmp_path, capsys):
    """--config 에 pack.yaml 이 아닌 이름의 팩 파일을 주면 옆의 pack.yaml 을 읽었다. test 는 경고 없이 다른 팩을
    시험했고, validate·scan 은 다른 파일의 해시를 적었다(실측)."""
    import hashlib
    import shutil

    pack = tmp_path / "pack"
    shutil.copytree(REPO / "policies/kr-core", pack)
    alt = pack / "alt.yaml"
    alt.write_text((pack / "pack.yaml").read_text(encoding="utf-8").replace("  id: kr-core", "  id: alt-pack", 1))
    digest = hashlib.sha256(alt.read_bytes()).hexdigest()[:16]

    assert main(["validate", str(alt)]) == 0
    assert f"(alt-pack)  해시 {digest}" in capsys.readouterr().out
    assert run(VIOLATING, "--config", str(alt), "--output-format", "json") == 1
    assert json.loads(capsys.readouterr().out)["run"]["pack_digest"] == digest
    suite = pack / "tests" / "pipa-22-2.test.yaml"
    assert main(["test", str(suite), "--config", str(alt), "--output-format", "json"]) == 0
    doc = json.loads(capsys.readouterr().out)["run"]
    assert (doc["pack"], doc["pack_digest"]) == ("alt-pack", digest)
    assert main(["test", str(suite), "--config", str(alt), "--no-color"]) == 0
    assert "alt.yaml" in capsys.readouterr().out, "보고서가 옆의 pack.yaml 을 가리키면 같은 혼동이 남는다"


def test_a_pack_file_tests_only_its_own_fixtures(tmp_path, capsys):
    """팩 파일 이름이 pack.yaml 이 아니면 test 가 폴더를 통째로 훑어, 옆에 둔 다른 팩의 테스트까지 모았다(검토에서
    실측). 경로를 주지 않으면 그 팩의 tests/ 만 본다."""
    import shutil

    shutil.copytree(REPO / "policies/kr-core/_legal", tmp_path / "_legal")
    (tmp_path / "tests").mkdir()
    shutil.copy(REPO / "policies/kr-core/tests/pipa-22-2.test.yaml", tmp_path / "tests")
    shutil.copytree(REPO / "policies/kr-core/tests/pipa-22-2", tmp_path / "tests" / "pipa-22-2")
    shutil.copytree(REPO / "policies/kr-core", tmp_path / "vendored")  # 다른 팩과 그 테스트
    team = tmp_path / "team.yaml"
    team.write_text((REPO / "policies/kr-core/pack.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    assert main(["test", "--config", str(team), "--output-format", "json"]) == 0
    fixtures = {r["file"] for r in json.loads(capsys.readouterr().out)["results"]}
    assert fixtures and all("vendored" not in f for f in fixtures)


def test_language_of():
    assert language_of(Path("a.tsx")) == "typescript"
    assert language_of(Path("a.js")) == "javascript"


# ── AI 경로 ─────────────────────────────────────────────────────────────────


def test_ai_no_overturns_a_weak_static_alternative():
    """이름만 그럴듯한 헬퍼를 AI 가 뒤집는다.

    guardian-call.ts 는 checkGuardianConsent 같은 이름 때문에 guardian-call(약한 대안)이 참이 된다.
    약한 근거는 혼자 경고를 풀지 못하고, AI 의 '아니오'가 그 자리를 대신한다."""
    from policypack.evaluate.engine import Target, evaluate
    from policypack.judge.fake import FakeJudge
    from policypack.pack.loader import load_pack
    from policypack.static.compile import compile_static
    from policypack.static.semgrep_cli import SemgrepBackend

    pack = load_pack(REPO / "policies/kr-core")
    f = REPO / FIX / "pipa-22-2" / "guardian-call.ts"
    static = SemgrepBackend().run(compile_static(pack), [f])
    res = evaluate(pack, [Target(path=f, lang="typescript")], static, judge=FakeJudge("아니오"))
    [u] = [x for x in res.findings if x.policy == "kr.pipa.22-2"]
    assert u.outcome.value == "needs-review"
    assert "대안 guardian-call: 정적 true" in u.trace
    assert "대안 ai-guard: AI 아니오 → false" in u.trace


def test_unasked_ai_alternative_is_not_reported_as_missing(capsys):
    """묻지 않은 AI 대안을 '찾지 못했다'고 적으면 안 된다. 평가하지 않았을 뿐이다."""
    run(f"{FIX}/network-act-50-3/violating.ts", "--no-color")
    out = capsys.readouterr().out
    assert "야간 시간대를 막는 검사가 없습니다" in out, "정적 대안은 판정했으니 적는다"
    assert "야간 발송을 막거나 야간 수신 동의를 확인하는 처리를 찾지 못했습니다" not in out


# ── 검사 범위의 빈틈 ────────────────────────────────────────────────────────


def test_unparsed_files_are_reported(tmp_path, capsys):
    """경고가 없다는 것이 "문제가 없다"가 아니라 "못 봤다"일 수 있다. 말해 줘야 한다."""
    broken = tmp_path / "broken.ts"
    broken.write_text("export function signUp(dto){ const age = dto.age;\n  if ( { ( ;;; <<<\n}\n", encoding="utf-8")
    run(str(broken), "--no-color", "--output-format", "concise")
    out = capsys.readouterr().out
    assert "파싱하지 못한 파일 1개" in out
    assert "broken.ts" in out


def test_unparsed_files_appear_in_json(tmp_path, capsys):
    broken = tmp_path / "broken.ts"
    broken.write_text("export function signUp(dto){ const age = dto.age;\n  if ( { ( ;;; <<<\n}\n", encoding="utf-8")
    run(str(broken), "--output-format", "json")
    data = json.loads(capsys.readouterr().out)
    assert len(data["run"]["unparsed"]) == 1


def test_clean_parse_reports_no_gaps(capsys):
    run(COMPLIANT, "--no-color", "--output-format", "concise")
    assert "파싱하지 못한" not in capsys.readouterr().out


def test_sarif_reports_coverage_gaps(tmp_path, monkeypatch, capsys):
    broken = tmp_path / "broken.ts"
    broken.write_text("export function signUp(dto){ const age = dto.age;\n  if ( { ( ;;; <<<\n}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    main(["scan", "broken.ts", "--output-format", "sarif"])
    inv = json.loads(capsys.readouterr().out)["runs"][0]["invocations"][0]
    assert inv["properties"]["coverageComplete"] is False
    notes = inv["toolExecutionNotifications"]
    # 파싱하지 못해 적용이 '모름'인 규칙은 AI 에게 물어야 하는데 판정자가 없다. 그것도 함께 알린다
    assert [n["descriptor"]["id"] for n in notes] == ["policypack/unparsed", "policypack/ai-pending"]
    assert notes[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "broken.ts"


def test_json_gap_paths_match_finding_paths(tmp_path, monkeypatch, capsys):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.ts").write_text("export function f(){ if ( { ( ;;; <<<\n}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    main(["scan", str(tmp_path / "sub"), "--output-format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert data["run"]["unparsed"] == ["sub/c.ts"]
    assert data["run"]["coverage_complete"] is False


def test_default_scan_survives_an_unparsable_file_that_needs_an_applicability_question(tmp_path, capsys):
    """판정자 없이 파싱이 안 되는 TSX 가 applies-ai 규칙(생성형 AI 사전 고지)에 걸리면 적용 질문을 하려다
    AttributeError 로 종료 코드 2 가 났다. 적용은 '모름'으로 남고 불확실로 보고돼야 한다."""
    f = tmp_path / "chat.tsx"
    f.write_text(
        'import OpenAI from "openai";\n'
        "const client = new OpenAI();\n"
        "export default function Chat() {\n"
        '  const r = client.chat.completions.create({ model: "x", messages: [] });\n'
        "  return <div>{r} & </ div>>> {{{ \n"
        "}\n",
        encoding="utf-8",
    )
    code = main(["scan", str(f), "--no-color", "--output-format", "json"])
    captured = capsys.readouterr()
    assert code in (0, 1), captured.err
    assert "내부 오류" not in captured.err
    report = json.loads(captured.out)
    assert any(x["outcome"] == "needs-review-uncertain" for x in report["findings"])


# ── 엔진과 판본은 보고서에 남는다 ────────────────────────────────────────────


def test_reports_name_the_engine_that_produced_them(capsys):
    """엔진이나 판이 바뀌면 결과가 달라질 수 있다. 보고서만 보고도 어느 엔진인지 알아야 한다."""
    from policypack.static.semgrep_cli import EXPECTED_VERSION

    run(f"{FIX}/pipa-22-2", "--output-format", "json", "--no-color")
    engine = json.loads(capsys.readouterr().out)["run"]["engine"]
    assert engine["name"] == "semgrep" and engine["version"].startswith(EXPECTED_VERSION)

    run(f"{FIX}/pipa-22-2", "--output-format", "sarif", "--no-color")
    ext = json.loads(capsys.readouterr().out)["runs"][0]["tool"]["extensions"]
    assert ext[0]["name"] == "semgrep" and ext[0]["version"].startswith(EXPECTED_VERSION)

    run(f"{FIX}/pipa-22-2", "--no-color")
    assert f"semgrep {EXPECTED_VERSION}" in capsys.readouterr().out


# ── 판정 기준 · 판정자 준비 ─────────────────────────────────────────────────


def test_fail_on_review_ignores_uncertain_only(capsys):
    """--fail-on review 는 확실한 '검토 필요'만 1 로 센다. 약한 대안만 있는 곳은 불확실이라 0 이다."""
    assert run(f"{FIX}/pipa-22-2/guardian-call.ts", "--fail-on", "review", "--no-color") == 0
    assert run(VIOLATING, "--fail-on", "review", "--no-color") == 1


def test_a_missing_claude_cli_is_a_setup_error(monkeypatch, capsys):
    """claude 가 없으면 모든 질문이 까닭 없이 실패로 남는다. 시작할 때 설정 오류로 알린다."""
    import policypack.judge.claude_cli as claude_cli

    monkeypatch.setattr(claude_cli, "BIN", "/nonexistent/claude")
    assert run(VIOLATING, "--judge", "claude-cli:haiku", "--no-color") == 2
    assert "claude 실행 파일을 찾지 못했습니다" in capsys.readouterr().err


def test_a_missing_api_key_is_a_setup_error(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert run(VIOLATING, "--judge", "anthropic:haiku", "--no-color") == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_a_judge_whose_binary_vanishes_fails_softly(monkeypatch):
    """준비를 통과한 뒤 실행 파일이 사라져도 도구 오류가 아니라 판정자 실패다."""
    import policypack.judge.claude_cli as claude_cli
    from policypack.judge.base import Question
    from policypack.judge.claude_cli import ClaudeCliJudge

    monkeypatch.setattr(claude_cli, "BIN", "/nonexistent/claude")
    q = Question(text="?", code="x", lang="typescript", policy="p", rule="r", predicate="a")
    assert ClaudeCliJudge("haiku").ask(q).failure == "transport"


def test_dates_in_a_rule_body_do_not_break_the_run(tmp_path, capsys):
    """YAML 은 2026-09-29 같은 값을 날짜로 읽는다. 컴파일한 Semgrep 설정에 그대로 넣으면 JSON 이 깨진다."""
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "pack.yaml").write_text(
        "apiVersion: policypack/v0.3\npack: {id: t, title: 시험}\ndefaults: {languages: [typescript]}\n"
        "policies:\n  - id: p1\n    category: c\n    title: 시험 정책\n    rules:\n      - id: r1\n"
        "        applies-when:\n          - {id: a1, static: {pattern-regex: 2026-09-29}}\n"
        "        compliant-if-any:\n"
        "          - {id: alt1, static: {pattern-regex: never}, on-unsatisfied: {message: m}}\n",
        encoding="utf-8",
    )
    (tmp_path / "a.ts").write_text("// 2026-09-29\nexport const a = 1;\n", encoding="utf-8")
    assert main(["scan", str(tmp_path / "a.ts"), "--config", str(pack), "--no-color"]) == 1


def test_usage_errors_are_reported_like_other_errors(capsys):
    with pytest.raises(SystemExit) as e:
        main(["scan", "--no-such-flag"])
    assert e.value.code == 2 and "오류:" in capsys.readouterr().err


def test_ctrl_c_is_one_line_not_a_traceback(monkeypatch, capsys):
    import policypack.cli as cli

    def interrupted(args):
        raise KeyboardInterrupt

    monkeypatch.setitem(cli.COMMANDS, "scan", interrupted)
    assert main(["scan", VIOLATING]) == 130
    assert "중단했습니다" in capsys.readouterr().err


def test_sarif_points_only_at_addresses_we_have(sarif):
    """우리가 갖지 않은 저장소 주소(github.com/policypack/policypack)를 도구 주소·도움말 주소로 넣었다."""
    driver = sarif["runs"][0]["tool"]["driver"]
    assert "informationUri" not in driver
    assert all(r.get("helpUri", "https://www.law.go.kr").startswith("https://www.law.go.kr") for r in driver["rules"])


def test_summary_names_files_by_their_report_path(tmp_path, monkeypatch, capsys):
    """이름만 적으면 index.ts 가 여럿인 저장소에서 어느 파일인지 모른다."""
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "index.ts").write_text("export const x = ;\n", encoding="utf-8")  # 파싱 실패
    monkeypatch.chdir(tmp_path)
    run(".", "--no-color")
    assert "a/b/index.ts" in capsys.readouterr().out


def test_a_named_file_no_rule_reads_is_not_a_gap(tmp_path, monkeypatch, capsys):
    """어떤 규칙의 언어도 아닌 파일(이름을 댄 deploy.sh)은 볼 규칙이 없어 건너뛴 것이다. 엔진이 끝내지 못한 것으로
    세자 규칙 9개가 모두 '불확실'이 됐다(검토에서 실측)."""
    (tmp_path / "deploy.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert run("deploy.sh", "--output-format", "json") == 0
    assert json.loads(capsys.readouterr().out)["run"]["incomplete"] == []


def test_the_same_file_has_one_report_path_however_it_is_named(tmp_path, monkeypatch, capsys):
    """`..` 가 남으면 같은 파일이 쓰기에 따라 다른 uri·지문이 된다."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.ts").write_text((REPO / VIOLATING).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path / "sub")

    def uris(*args):
        run(*args, "--output-format", "json")
        return {f["file"] for f in json.loads(capsys.readouterr().out)["findings"]}

    assert uris("../sub") == uris(".") == uris(str(tmp_path / "sub" / "a.ts"))


def test_sarif_rule_descriptions_are_always_text(tmp_path, capsys):
    """rationale 에 motivation 만 있으면 fullDescription.text 가 null 이 되어 SARIF 가 스키마에 어긋났다."""
    import re
    import shutil

    pack = tmp_path / "pack"
    shutil.copytree(REPO / "policies/kr-core", pack, ignore=shutil.ignore_patterns("tests"))
    text = (pack / "pack.yaml").read_text(encoding="utf-8")
    stripped = re.sub(r"^      implementation:.*\n", "", text, count=1, flags=re.M)  # motivation 만 남긴다
    assert stripped != text
    (pack / "pack.yaml").write_text(stripped, encoding="utf-8")
    run(VIOLATING, "--config", str(pack), "--output-format", "sarif")
    rules = json.loads(capsys.readouterr().out)["runs"][0]["tool"]["driver"]["rules"]
    assert all(isinstance(r["fullDescription"]["text"], str) for r in rules)
