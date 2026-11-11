"""정책 팩 문법 v0.4 검증.

실제로 쓰는 팩(policies/kr-core)이 읽히는지, 그리고 잘못된 팩이 **조용히 통과하지
않는지**를 본다. 후자가 더 중요하다. 오타 난 조건이 조용히 빠지면 규칙이 꺼진 줄
모르고 쓰게 된다.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

import pytest
from pydantic import BaseModel

from policypack.errors import PackError
from policypack.model import LegalRef, PolicyPack
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


def test_effective_from_is_the_date_printed_in_the_pinned_text(pack):
    """effective-from 은 받은 판본의 시행일이다. 손으로 적은 날짜가 원문과 어긋나면 안 된다.

    2026-10-06 까지 시행령 제23조에는 부칙에서 읽은 날짜(2026-01-22)가 손으로 적혀 있었다. 부칙은
    고정하지 않은 글이라 보고서의 '시행' 줄이 확인할 수 없는 말이 됐다.

    보고서의 근거 줄에 나가는 법 이름과 조도 원문 첫 줄과 같아야 한다(항은 보지 않는다).
    """
    for policy in pack.policies:
        for ref in policy.legal.violated_when_failed:
            head = (KR_CORE / ref.text_file).read_text(encoding="utf-8").splitlines()[:3]
            assert head[0].startswith(f"{ref.statute} {ref.article}("), f"{policy.id}: 원문 첫 줄 {head[0]}"
            printed = [m.group(1) for line in head if (m := re.fullmatch(r"시행 (\d{4}-\d{2}-\d{2})", line))]
            assert printed == [ref.effective_from.isoformat()], f"{policy.id}/{ref.article}: 원문 머리 {printed}"


# 조와 별표의 번호. 이용자에게 보이는 글에 나오면 그 정책이 원문을 고정한 조문이어야 한다.
CITED = re.compile(r"제\s*\d+\s*조(?:의\s*\d+)?|별표\s*\d+")
# 부칙과 제재. 고정한 원문에 그 낱말이 있을 때만 쓴다.
UNPINNED_TALK = re.compile(r"부칙|과태료|과징금|벌금|징역|벌칙|처벌|시정명령")
# 고정한 조문이 가리키기만 하고 원문은 팩에 없는 것. 원문을 _legal 에 고정하면 여기서 지운다.
POINTED_ONLY = {"kr.network-act.50-4": {"별표6"}}
NOT_PROSE = {"id", "category", "languages", "anchor_on"}


def _prose(node, where=""):
    """모델을 훑어 사람이 읽는 글을 낸다. 식별자, Semgrep 패턴(dict), 조문 참조는 글이 아니다.

    칸 이름을 하나씩 적지 않는다. 문법에 글 칸이 새로 생겨도 빠지지 않아야 한다.
    """
    if isinstance(node, (LegalRef, Enum)):
        return
    if isinstance(node, BaseModel):
        here = f"{where}/{node.id}" if isinstance(getattr(node, "id", None), str) else where
        for name in type(node).model_fields:
            if name not in NOT_PROSE:
                yield from _prose(getattr(node, name), f"{here}.{name}")
    elif isinstance(node, list):
        for item in node:
            yield from _prose(item, where)
    elif isinstance(node, str):
        yield where, node


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def test_visible_text_cites_only_what_the_policy_pins(pack):
    """이용자에게 보이는 글은 그 정책이 원문을 고정한 조문만 번호로 가리킨다.

    2026-10-06 점검: 고정하지 않은 제43조의 과태료 금액, 부칙, 제2조·제4조가 보고서에 실리고 있었다.
    틀린 말이 아니어도 원문과 대조할 길이 없다. 고치는 길은 둘이다. 원문을 받아 violated-when-failed 에
    넣거나, 그 말을 YAML 주석으로 옮긴다.

    보는 것은 조·별표의 번호와 낱말 몇 개뿐이다. 항·호가 맞는지, 어느 법의 조문인지, 번호 없이 적은
    날짜·금액·해석은 보지 않는다. 걸러내는 그물이지 증명이 아니다.
    """
    kinds = set()
    for policy in pack.policies:
        refs = policy.legal.violated_when_failed
        pinned = {_squash(ref.article) for ref in refs} | POINTED_ONLY.get(policy.id, set())
        texts = "".join((KR_CORE / ref.text_file).read_text(encoding="utf-8") for ref in refs)
        for where, text in _prose(policy):
            kinds.add(where.rsplit(".", 1)[-1])
            loose = {_squash(m.group(0)) for m in CITED.finditer(text)} - pinned
            loose |= {word for word in UNPINNED_TALK.findall(text) if word not in texts}
            assert not loose, f"{where.lstrip('/')}: 고정한 원문에 없는 {sorted(loose)}"
    missed = {"title", "ask_developer", "motivation", "implementation", "question", "message", "remediation"} - kinds
    assert not missed, f"_prose 가 찾지 못한 글 칸: {sorted(missed)}"


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
apiVersion: policypack/v0.4
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
        (MINIMAL.replace("policypack/v0.4", "policypack/v0.3"), "옛 판은 거부"),
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


# ── 의무 지도 (v0.4) ────────────────────────────────────────────────────────

WITH_DUTY = MINIMAL.replace("    title: 시험 정책\n", "    title: 시험 정책\n    duties: [pipa-22-2-1]\n")


def test_kr_core_duties_point_into_its_catalog(pack):
    from policypack.pack.loader import load_duties

    have = load_duties(KR_CORE)
    assert all(pol.duties for pol in pack.policies), "kr-core 의 정책은 모두 의무를 가리킨다"
    assert {d for pol in pack.policies for d in pol.duties} == set(have)
    for row in have.values():
        assert row["quote"] and row["duty_ko"] and row["source_url"].startswith("https://www.law.go.kr/")


def test_duty_must_exist_in_pack_folder(tmp_path):
    p = _write(tmp_path, WITH_DUTY)
    with pytest.raises(PackError, match="p1 → pipa-22-2-1"):
        load_pack(p)
    (tmp_path / "_duties.jsonl").write_text('{"id": "pipa-22-2-1", "duty_ko": "d"}\n', encoding="utf-8")
    assert load_pack(p).policies[0].duties == ["pipa-22-2-1"]


@pytest.mark.parametrize(
    "body,match",
    [
        ('{"id": "pipa-22-2-1"}\n{"id": "pipa-22-2-1"}\n', "중복"),
        ("not json\n", "JSON 이 아닙니다"),
        ('["pipa-22-2-1"]\n', "id 가 있는 객체"),
    ],
)
def test_bad_duty_files_are_rejected(tmp_path, body, match):
    (tmp_path / "_duties.jsonl").write_text(body, encoding="utf-8")
    with pytest.raises(PackError, match=match):
        load_pack(_write(tmp_path, WITH_DUTY))


@pytest.mark.parametrize("bad", ["PIPA-22", "pipa", "pipa 22-2", "pipa-22-2-1, x"])
def test_duty_id_shape(tmp_path, bad):
    with pytest.raises(PackError):
        load_pack(_write(tmp_path, WITH_DUTY.replace("[pipa-22-2-1]", f"['{bad}']")))


def test_duplicate_duty_ids_rejected(tmp_path):
    with pytest.raises(PackError, match="중복"):
        load_pack(_write(tmp_path, WITH_DUTY.replace("[pipa-22-2-1]", "[pipa-22-2-1, pipa-22-2-1]")))


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


def test_validate_also_runs_the_function_boundary_rule_through_the_engine(monkeypatch, capsys):
    """검사는 함수 단위 규칙이 걸리는 파일이 있을 때만 함수 경계 규칙을 엔진에 넘긴다. validate 가 같은 길을 타면
    빈 파일 하나로는 경계 규칙이 엔진에 가지 않아, 엔진이 거절할 경계 패턴을 통과시켰다(검토에서 실측)."""
    from policypack.cli import main
    from policypack.static import compile as compile_mod

    assert main(["validate", str(KR_CORE)]) == 0
    capsys.readouterr()
    broken = {lang: ["function $F(( { ... }"] for lang in compile_mod.REGION_PATTERNS}
    monkeypatch.setattr(compile_mod, "REGION_PATTERNS", broken)
    assert main(["validate", str(KR_CORE)]) == 2
    assert "정적 조건이 잘못됐습니다" in capsys.readouterr().err


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
    # report-1.json·review-2.json 은 손으로 쓴 보고서 스키마다(모델이 없다). tests/test_report_schema.py 와
    # tests/test_review.py 가 실제 보고서로 검사한다
    handwritten = ["report-1.json", "review-2.json"]
    assert sorted(p.name for p in (REPO / "schemas").glob("*.json")) == sorted([*SCHEMAS, *handwritten])


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
    assert not (tmp_path / "schemas" / "policy-pack-0.4.json").exists()


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


@pytest.mark.parametrize("text_file", ["../outside.txt", "/etc/hosts", "_legal/../../x.txt", "C:\\law.txt"])
def test_a_statute_text_must_live_inside_the_pack(tmp_path, text_file):
    """text-file 이 팩 밖을 가리키면 SARIF 가 그 파일 내용을 조문으로 실었다(끝까지 점검에서 실측)."""
    bad = MINIMAL.replace(
        "    rules:\n",
        "    legal:\n      violated-when-failed:\n"
        f"        - {{statute: 법, article: 제1조, text-file: '{text_file}'}}\n"
        "    rules:\n",
        1,
    )
    with pytest.raises(PackError, match="팩 폴더 안의 상대 경로"):
        load_pack(_write(tmp_path, bad))


def test_a_changed_statute_text_is_not_embedded_in_sarif(tmp_path):
    """해시가 다르면 팩이 말하는 조문이 아니다. validate 가 알리고, SARIF 는 싣지 않는다."""
    import shutil

    from policypack.report.sarif import _statute_text

    copy = tmp_path / "kr-core"
    shutil.copytree(KR_CORE, copy, ignore=shutil.ignore_patterns("tests"))
    ref = load_pack(copy).policies[0].legal.violated_when_failed[0]
    assert "제22조의2" in _statute_text(ref, copy)
    (copy / ref.text_file).write_text("다른 글\n", encoding="utf-8")
    assert _statute_text(ref, copy) == ""


def test_pack_keys_are_kebab_case_only(tmp_path):
    """파이썬 이름(compliant_if_any)도 받으면 CLI 는 통과하고 편집기(스키마)는 거절해 둘이 어긋났다."""
    with pytest.raises(PackError):
        load_pack(_write(tmp_path, MINIMAL.replace("compliant-if-any", "compliant_if_any")))


def test_the_committed_schemas_accept_what_kr_core_writes():
    """편집기는 커밋한 스키마로 검사한다. kr-core 의 테스트 파일은 모두 `ai: {ai-guard: no}` 줄임 꼴을 쓰는데
    테스트 스키마가 객체만 받아 파일마다 오류를 냈다(끝까지 점검에서 실측)."""
    import datetime
    import json

    jsonschema = pytest.importorskip("jsonschema")
    from ruamel.yaml import YAML

    def plain(x):  # YAML 이 날짜로 읽은 값. 편집기는 글자로 본다
        if isinstance(x, dict):
            return {k: plain(v) for k, v in x.items()}
        if isinstance(x, list):
            return [plain(v) for v in x]
        return x.isoformat() if isinstance(x, datetime.date) else x

    y = YAML(typ="safe", pure=True)
    pairs = [("policy-pack-0.4.json", KR_CORE / "pack.yaml")] + [
        ("policy-test-0.1.json", f) for f in sorted((KR_CORE / "tests").glob("*.test.yaml"))
    ]
    for schema_name, f in pairs:
        schema = json.loads((REPO / "schemas" / schema_name).read_text(encoding="utf-8"))
        doc = plain(y.load(f.read_text(encoding="utf-8")))
        errors = list(jsonschema.Draft202012Validator(schema).iter_errors(doc))
        assert errors == [], f"{f.name}: {errors[0].message if errors else ''}"


def test_a_pack_file_that_cannot_be_read_is_a_clear_error(tmp_path, capsys):
    """UTF-8 이 아니거나 폴더인 pack.yaml 은 traceback 이 아니라 오류 한 줄이다."""
    from policypack.cli import main

    (tmp_path / "pack.yaml").write_bytes("# 한국어\n".encode("euc-kr") + MINIMAL.encode())
    assert main(["validate", str(tmp_path)]) == 2
    assert "UTF-8 로 읽지 못했습니다" in capsys.readouterr().err
    (tmp_path / "pack.yaml").unlink()
    (tmp_path / "pack.yaml").mkdir()
    assert main(["validate", str(tmp_path)]) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_doctor_fails_when_the_default_pack_is_broken(tmp_path, monkeypatch, capsys):
    """기본 팩을 읽지 못하면 scan·test 가 모두 실패한다. doctor 가 먼저 알린다."""
    import json

    from policypack.cli import main

    monkeypatch.setenv("POLICYPACK_PACK", str(tmp_path / "missing"))
    assert main(["doctor", "--json"]) == 2
    info = json.loads(capsys.readouterr().out)
    assert info["pack_ok"] is False and any("정책 팩" in n for n in info["notes"])


def test_validate_warns_about_statute_texts_it_cannot_use(tmp_path, capsys):
    """폴더를 가리키거나 UTF-8 이 아닌 원문은 traceback 이나 깨진 SARIF 가 아니라 경고다."""
    import hashlib
    import shutil

    from policypack.cli import main

    copy = tmp_path / "kr-core"
    shutil.copytree(KR_CORE, copy, ignore=shutil.ignore_patterns("tests"))
    target = copy / "_legal" / "pipa-22-2.txt"
    old = hashlib.sha256(target.read_bytes()).hexdigest()
    data = target.read_text(encoding="utf-8").encode("cp949", errors="replace")
    target.write_bytes(data)
    text = (copy / "pack.yaml").read_text(encoding="utf-8")
    assert old in text
    (copy / "pack.yaml").write_text(text.replace(old, hashlib.sha256(data).hexdigest()), encoding="utf-8")
    assert main(["validate", str(copy)]) == 0
    assert "UTF-8 이 아니라 SARIF 에 싣지 않습니다" in capsys.readouterr().out


def test_doctor_fails_on_a_bad_timeout_setting(monkeypatch, capsys):
    from policypack.cli import main

    monkeypatch.setenv("POLICYPACK_SEMGREP_TIMEOUT", "abc")
    assert main(["doctor"]) == 2
    assert "POLICYPACK_SEMGREP_TIMEOUT" in capsys.readouterr().out
