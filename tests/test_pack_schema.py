"""정책 팩 문법 v0.3 검증.

실제로 쓰는 팩(policies/kr-core)이 읽히는지, 그리고 잘못된 팩이 **조용히 통과하지
않는지**를 본다. 후자가 더 중요하다. 오타 난 조건이 조용히 빠지면 규칙이 꺼진 줄
모르고 쓰게 된다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from policypack.errors import PackError
from policypack.model import PolicyPack
from policypack.pack.loader import check_legal_texts, check_review_dates, load_pack, pack_digest

REPO = Path(__file__).resolve().parents[1]
KR_CORE = REPO / "policies" / "kr-core"


@pytest.fixture(scope="module")
def pack() -> PolicyPack:
    return load_pack(KR_CORE)


# ── 실제 팩 ─────────────────────────────────────────────────────────────────


def test_kr_core_loads(pack):
    assert pack.pack.id == "kr-core"
    assert [p.id for p in pack.policies][:3] == [
        "kr.pipa.22-2",
        "kr.network-act.50-3",
        "kr.ai-basic-act.31",
    ]


def test_every_alternative_explains_itself(pack):
    """대안마다 '왜 이게 아닌지'와 개발자에게 할 질문이 있어야 한다."""
    for pol, rule in pack.iter_rules():
        for p in rule.compliant_if_any:
            assert p.on_unsatisfied is not None, f"{pol.id}/{rule.id}/{p.id} 에 on-unsatisfied 가 없다"
            assert p.on_unsatisfied.message


def test_regex_only_predicates_are_marked_parse_independent(pack):
    """정규식만 쓰는 조건은 파싱 실패와 무관하게 값을 내야 한다.

    실측: 파일 전체가 Syntax error 면 languages 가 붙은 정규식 규칙도 매치되지 않는다.
    그래서 이런 조건은 generic 사본으로 따로 컴파일한다.
    """
    preds = [q for _, rule in pack.iter_rules() for q in list(rule.applies_when) + list(rule.compliant_if_any)]
    regex_only = [p for p in preds if p.static and set(p.static) == {"pattern-regex"}]
    assert regex_only
    for p in regex_only:
        assert p.parse_independent, p.id


def test_digest_is_stable_and_short(pack):
    d = pack_digest(KR_CORE)
    assert len(d) == 16 and d == pack_digest(KR_CORE / "pack.yaml")


# ── validate 가 내는 경고 ───────────────────────────────────────────────────


def test_legal_texts_are_verified(pack):
    """모든 조문의 원문 파일이 커밋돼 있고 해시가 팩에 적힌 값과 맞아야 한다.

    경고가 하나라도 남아 있으면 '근거 조문이 있다'고 말할 수 없다.
    """
    assert check_legal_texts(pack, KR_CORE) == []


def test_every_statute_records_its_version(pack):
    """어느 판본을 보고 규칙을 썼는지가 팩 안에 남아야 한다."""
    for policy in pack.policies:
        for ref in policy.legal.violated_when_failed:
            label = f"{policy.id}/{ref.article}"
            assert ref.text_sha256 and len(ref.text_sha256) == 64, label
            assert ref.text_retrieved, label
            assert ref.effective_from, label
            assert ref.law_id, label


def test_amended_statute_is_detected(pack, tmp_path):
    """법이 개정되면 경고가 나야 한다. 이 장치의 존재 이유다.

    실제 팩을 건드리지 않고, 원문만 한 글자 고친 사본으로 확인한다.
    """
    import shutil

    copy = tmp_path / "kr-core"
    shutil.copytree(KR_CORE, copy)
    target = copy / "_legal" / "pipa-22-2.txt"
    target.write_text(target.read_text(encoding="utf-8").replace("만 14세", "만 19세", 1), encoding="utf-8")

    warnings = check_legal_texts(load_pack(copy), copy)
    assert len(warnings) == 1
    assert "원문이 바뀌었습니다" in warnings[0]


def test_review_dates_are_set(pack):
    assert check_review_dates(pack) == []


# ── 잘못된 팩은 거부된다 ────────────────────────────────────────────────────

MINIMAL = """
apiVersion: policypack/v0.3
pack: {id: t, title: 시험}
policies:
  - id: p1
    category: c
    title: 시험 정책
    rules:
      - id: r1
        applies-when:
          - {id: a1, static: {pattern-regex: foo}}
        compliant-if-any:
          - {id: alt1, static: {pattern-regex: bar}, on-unsatisfied: {message: m}}
"""


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "pack.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_minimal_pack_is_valid(tmp_path):
    assert load_pack(_write(tmp_path, MINIMAL)).policies[0].id == "p1"


@pytest.mark.parametrize(
    "bad,why",
    [
        (MINIMAL.replace("policypack/v0.3", "policypack/v0.2"), "옛 판은 거부"),
        (MINIMAL.replace("pattern-regex: foo", "patern-regex: foo"), "오타 난 Semgrep 키"),
        (MINIMAL.replace("static: {pattern-regex: foo}", "statik: {pattern-regex: foo}"), "모르는 필드"),
        (MINIMAL.replace("{id: a1, static: {pattern-regex: foo}}", "{id: a1}"), "조건 몸통이 없음"),
        (
            MINIMAL.replace(
                "{id: a1, static: {pattern-regex: foo}}",
                "{id: a1, static: {pattern-regex: foo}, ai: {question: q}}",
            ),
            "static 과 ai 를 둘 다",
        ),
        (
            MINIMAL.replace("          - {id: alt1, static: {pattern-regex: bar}, on-unsatisfied: {message: m}}", ""),
            "대안이 없음",
        ),
        (
            MINIMAL.replace(
                "{id: alt1, static: {pattern-regex: bar}, on-unsatisfied: {message: m}}",
                "{id: alt1, ai: {question: q}}",
            ),
            "대안이 전부 AI",
        ),
    ],
)
def test_bad_packs_are_rejected(tmp_path, bad, why):
    with pytest.raises(PackError):
        load_pack(_write(tmp_path, bad))


def test_duplicate_ids_are_rejected(tmp_path):
    dup = MINIMAL.replace(
        "          - {id: alt1, static: {pattern-regex: bar}, on-unsatisfied: {message: m}}",
        "          - {id: alt1, static: {pattern-regex: bar}, on-unsatisfied: {message: m}}\n"
        "          - {id: alt1, static: {pattern-regex: baz}, on-unsatisfied: {message: m}}",
    )
    with pytest.raises(PackError, match="중복"):
        load_pack(_write(tmp_path, dup))


def test_yaml_11_booleans_are_not_coerced(tmp_path):
    """pyyaml(YAML 1.1)이면 no 가 False 로 바뀐다. ruamel(1.2)은 문자열로 둔다.

    정책 팩에는 '예/아니오' 같은 답과 on/off 가 들어갈 수 있어서 이 차이가 조용한 버그가 된다.
    """
    text = MINIMAL.replace("{id: a1, static: {pattern-regex: foo}}", '{id: no, static: {pattern-regex: "on"}}')
    pack = load_pack(_write(tmp_path, text))
    pred = pack.policies[0].rules[0].applies_when[0]
    assert pred.id == "no" and pred.static["pattern-regex"] == "on"


# 문법 v0.3 에서 지운 키. 남아 있으면 모르는 키로 거부돼야 한다(extra="forbid").
REMOVED = [
    (
        "judges",
        MINIMAL.replace("pack: {id: t, title: 시험}\n", "pack: {id: t, title: 시험}\njudges: {on-failure: exclude}\n"),
    ),
    ("pack.owner", MINIMAL.replace("pack: {id: t, title: 시험}", "pack: {id: t, title: 시험, owner: x}")),
    ("use-case", MINIMAL.replace("    title: 시험 정책\n", "    title: 시험 정책\n    use-case: {any-of: [x]}\n")),
    ("context", MINIMAL.replace("      - id: r1\n", "      - id: r1\n        context: callees\n")),
    ("polarity", MINIMAL.replace("{id: a1, static:", "{id: a1, polarity: raise-only, static:")),
    ("capture", MINIMAL.replace("{id: a1, static:", "{id: a1, capture: [X], static:")),
    ("on-satisfied", MINIMAL.replace("{id: alt1, static:", "{id: alt1, on-satisfied: s, static:")),
    (
        "remediation.effort",
        MINIMAL.replace(
            "on-unsatisfied: {message: m}", "on-unsatisfied: {message: m, remediation: {effort: low, text: t}}"
        ),
    ),
    (
        "ai.min-judge-tier",
        MINIMAL.replace(
            "on-unsatisfied: {message: m}}",
            "on-unsatisfied: {message: m}}\n          - {id: alt2, ai: {question: q, min-judge-tier: t}}",
        ),
    ),
    (
        "ai.inputs",
        MINIMAL.replace(
            "on-unsatisfied: {message: m}}",
            "on-unsatisfied: {message: m}}\n          - {id: alt2, ai: {question: q, inputs: [X]}}",
        ),
    ),
    (
        "applies-ai.min-judge-tier",
        MINIMAL.replace("      - id: r1\n", "      - id: r1\n        applies-ai: {question: q, min-judge-tier: t}\n"),
    ),
    ("rationale.short", MINIMAL.replace("    title: 시험 정책\n", "    title: 시험 정책\n    rationale: {short: s}\n")),
    (
        "review.owner",
        MINIMAL.replace(
            "    title: 시험 정책\n", "    title: 시험 정책\n    review: {review-by: 2030-01-01, owner: x}\n"
        ),
    ),
    (
        "legal.secondary-refs",
        MINIMAL.replace(
            "    title: 시험 정책\n",
            "    title: 시험 정책\n"
            "    legal: {violated-when-failed: [{statute: s, article: 제1조}], secondary-refs: [{title: t}]}\n",
        ),
    ),
    (
        "legal.effective-to",
        MINIMAL.replace(
            "    title: 시험 정책\n",
            "    title: 시험 정책\n"
            "    legal: {violated-when-failed: [{statute: s, article: 제1조, effective-to: 2030-01-01}]}\n",
        ),
    ),
]


@pytest.mark.parametrize("text", [t for _, t in REMOVED], ids=[k for k, _ in REMOVED])
def test_removed_keys_are_refused(tmp_path, text):
    """읽지 않는 키를 적어 두면 동작하는 줄 안다. 지운 키는 모르는 키로 거부한다."""
    assert text != MINIMAL
    with pytest.raises(PackError):
        load_pack(_write(tmp_path, text))


# ── 명령 ────────────────────────────────────────────────────────────────────


def test_validate_passes_on_kr_core(capsys):
    from policypack.cli import main

    assert main(["validate", "--strict"]) == 0
    assert "문법에 맞고, 미완인 곳도 없습니다" in capsys.readouterr().out


def test_validate_reports_an_amended_statute(tmp_path, capsys):
    """커밋한 조문 원문이 바뀌면 validate 가 알린다. --strict 면 실패다."""
    import shutil

    from policypack.cli import main

    copy = tmp_path / "kr-core"
    shutil.copytree(KR_CORE, copy, ignore=shutil.ignore_patterns("tests"))
    target = copy / "_legal" / "pipa-22-2.txt"
    target.write_text(target.read_text(encoding="utf-8").replace("만 14세", "만 19세", 1), encoding="utf-8")
    assert main(["validate", str(copy)]) == 0
    assert "원문이 바뀌었습니다" in capsys.readouterr().out
    assert main(["validate", str(copy), "--strict"]) == 1


@pytest.mark.parametrize(
    "broken",
    [
        {"pattern-regex: foo": 'pattern-regex: "(foo"'},  # 괄호가 빠진 정규식
        {"{pattern-regex: bar}": '{pattern: "bar(("}'},  # 구문 오류 패턴
        {"pack: {id: t, title: 시험}": "pack: {id: t, title: 시험}\ndefaults: {languages: [javscript]}"},  # 없는 언어
    ],
)
def test_validate_runs_the_static_conditions_through_the_engine(tmp_path, capsys, broken):
    """문법 검사(pydantic)는 패턴·정규식·언어 이름을 읽지 않는다. 그래서 validate 가 '문법에 맞습니다'라고 한 팩을
    scan 이 거절했다(끝까지 점검에서 실측). 규칙 오류는 엔진의 임시 경로가 아니라 팩의 이름으로 적는다."""
    from policypack.cli import main

    text = MINIMAL
    for old, new in broken.items():
        assert old in text
        text = text.replace(old, new, 1)
    _write(tmp_path, text)
    assert main(["validate", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "정적 조건이 잘못됐습니다" in err
    if " in rule " in err:
        # semgrep 은 id 앞에 임시 폴더 경로를 점으로 붙인다(macOS var.folders…, 리눅스 tmp.…). 팩의 이름만 남긴다
        assert " in rule p1.r1." in err


def test_validate_warns_about_languages_a_folder_scan_never_selects(tmp_path, capsys):
    """Semgrep 이 아는 언어여도(rust) 폴더 검사는 그 파일을 고르지 않는다. 팩이 조용히 아무것도 검사하지 않았다."""
    from policypack.cli import main

    _write(
        tmp_path,
        MINIMAL.replace("pack: {id: t, title: 시험}", "pack: {id: t, title: 시험}\ndefaults: {languages: [rust]}"),
    )
    assert main(["validate", str(tmp_path)]) == 0
    assert "rust 파일은 폴더 검사에서 고르지 않습니다" in capsys.readouterr().out
    assert main(["validate", str(tmp_path), "--strict"]) == 1


def test_committed_schemas_match_the_model_and_nothing_else_is_there():
    """커밋한 schemas/ 가 모델과 같고, 지운 문법의 스키마 파일이 남아 있지 않다."""
    from policypack.cli import SCHEMAS, main

    assert main(["schema", "--check"]) == 0
    assert sorted(p.name for p in (REPO / "schemas").glob("*.json")) == sorted(SCHEMAS)


def test_doctor_finds_the_engine(capsys):
    import json

    from policypack.cli import main

    assert main(["doctor", "--json"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["path"] and info["version"]


def test_an_expired_review_date_is_reported():
    import datetime as dt

    pack = load_pack(REPO / "policies" / "kr-core")
    later = [w for w in check_review_dates(pack, today=dt.date(2100, 1, 1)) if "지났습니다" in w]
    assert len(later) == len(pack.policies)


def test_schema_refuses_to_run_outside_a_source_checkout(tmp_path, monkeypatch, capsys):
    """설치본에서 돌리면 SCHEMA_DIR 가 엉뚱한 곳을 가리킨다. 거기 만들거나 지우면 안 된다."""
    import policypack.cli as cli

    monkeypatch.setattr(cli, "SCHEMA_DIR", tmp_path / "schemas")
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas" / "openapi.json").write_text("{}", encoding="utf-8")
    assert cli.main(["schema", "--write"]) == 2
    assert (tmp_path / "schemas" / "openapi.json").exists()
    assert not (tmp_path / "schemas" / "policy-pack-0.3.json").exists()


def test_schema_write_removes_only_our_stale_files(tmp_path, monkeypatch):
    import policypack.cli as cli

    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "src" / "policypack").mkdir(parents=True)
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    (schemas / "policy-pack-0.2.json").write_text("{}", encoding="utf-8")
    (schemas / "other.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "SCHEMA_DIR", schemas)
    assert cli.main(["schema", "--write"]) == 0
    assert sorted(p.name for p in schemas.glob("*.json")) == ["other.json", *sorted(cli.SCHEMAS)]
