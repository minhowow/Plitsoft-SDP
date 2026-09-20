"""Semgrep 오류 분류 — 시제품의 잠재 크래시에 대한 회귀 시험.

시제품은 `errors[]` 를 이렇게 갈랐다.

    broken      = {basename(e["path"]) for e in errors if e.get("path")}
    rule_errors = [... for e in errors if not e.get("path")]
    if rule_errors: raise RuntimeError(...)

그런데 PartialParsing 오류에는 최상위 `path` 가 없다. 경로가 `type` 안의 스팬 목록에
중첩돼 있다. 그래서 파일 일부가 파싱되지 않는 평범한 저장소를 스캔하면 "정책 팩의
정적 조건 오류"라며 즉시 터진다.

아래 JSON 은 semgrep 1.176 의 실제 출력 모양이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from policypack.static.backend import PredicateKey
from policypack.static.parse import parse_semgrep_json

META = {
    "policypack": {
        "policy": "kr.pipa.22-2",
        "rule": "signup-without-guard",
        "group": "applies-when",
        "predicate": "signup-context",
    }
}


def _result(path="/t/a.ts", **extra):
    return {
        "check_id": "tmp1234.kr.pipa.22-2.signup-without-guard.signup-context",
        "path": path,
        "start": {"line": 2, "col": 17, "offset": 45},
        "end": {"line": 5, "col": 3, "offset": 181},
        "extra": {"metadata": META, "message": "signup-context", **extra},
    }


# 실제 출력: type 이 목록이고 경로가 스팬 안에 있다
PARTIAL_PARSING = {
    "type": [
        "PartialParsing",
        [
            {
                "path": "/t/broken.ts",
                "start": {"line": 2, "col": 3, "offset": 0},
                "end": {"line": 2, "col": 13, "offset": 10},
            },
            {
                "path": "/t/broken.ts",
                "start": {"line": 2, "col": 16, "offset": 0},
                "end": {"line": 2, "col": 19, "offset": 3},
            },
        ],
    ],
    "level": "warn",
}

SYNTAX_ERROR = {"type": "Syntax error", "path": "/t/dead.js", "level": "warn", "message": "Syntax error"}

BAD_RULE = {"type": "Invalid rule schema", "level": "error", "message": "rule 'x' has no pattern"}


def test_partial_parsing_is_not_a_rule_error():
    """이 한 줄이 시제품에서는 RuntimeError 였다."""
    res = parse_semgrep_json({"results": [], "errors": [PARTIAL_PARSING]})
    assert res.rule_errors == [], "PartialParsing 은 규칙 오류가 아니다"
    assert res.partial_unparsed == {Path("/t/broken.ts"): res.partial_unparsed[Path("/t/broken.ts")]}
    assert len(res.partial_unparsed[Path("/t/broken.ts")]) == 2
    assert res.hard_unparsed == set(), "일부 파싱 실패는 파일 전체 실패와 다르다"


def test_syntax_error_marks_the_whole_file():
    res = parse_semgrep_json({"results": [], "errors": [SYNTAX_ERROR]})
    assert res.hard_unparsed == {Path("/t/dead.js")}
    assert res.rule_errors == []


def test_real_rule_error_is_still_reported():
    """우리가 만든 규칙이 잘못된 것은 여전히 드러나야 한다. 이건 우리 문제다."""
    res = parse_semgrep_json({"results": [], "errors": [BAD_RULE]})
    assert len(res.rule_errors) == 1
    assert "Invalid rule schema" in res.rule_errors[0]


def test_mixed_errors_are_sorted_correctly():
    res = parse_semgrep_json({"results": [], "errors": [PARTIAL_PARSING, SYNTAX_ERROR, BAD_RULE]})
    assert res.hard_unparsed == {Path("/t/dead.js")}
    assert list(res.partial_unparsed) == [Path("/t/broken.ts")]
    assert len(res.rule_errors) == 1


def test_match_is_keyed_by_metadata_not_check_id():
    """check_id 에는 설정 파일 경로가 앞에 붙는다(tmp1234.). 부분 문자열로 되짚지 않는다."""
    res = parse_semgrep_json({"results": [_result()], "errors": []})
    assert len(res.matches) == 1
    m = res.matches[0]
    assert (m.key.policy, m.key.rule, m.key.predicate) == (
        "kr.pipa.22-2",
        "signup-without-guard",
        "signup-context",
    )
    assert m.key.group == "applies-when"


def test_line_range_survives_even_though_lines_are_hidden():
    """CE 는 로그인 전이면 extra.lines 를 'requires login' 으로 가린다.

    하지만 start/end 의 line·col·offset 은 항상 채워진다(실측). 판정을 특정 줄에
    걸고 SARIF region 을 채우는 데는 이것으로 충분하다.
    """
    res = parse_semgrep_json({"results": [_result(lines="requires login")], "errors": []})
    span = res.matches[0].span
    assert (span.start.line, span.start.col, span.start.offset) == (2, 17, 45)
    assert (span.end.line, span.end.offset) == (5, 181)


def test_match_without_our_metadata_is_flagged():
    """policypack 메타데이터가 없는 매치는 컴파일 쪽 버그다. 조용히 넘기지 않는다."""
    bad = _result()
    bad["extra"]["metadata"] = {}
    res = parse_semgrep_json({"results": [bad], "errors": []})
    assert res.matches == []
    assert "메타데이터가 없습니다" in res.rule_errors[0]


def test_empty_output():
    res = parse_semgrep_json({})
    assert res.matches == [] and res.rule_errors == [] and res.hard_unparsed == set()


# ── 시간 초과는 규칙 하나의 일이다 ─────────────────────────────────────────


def _timeout(rule_id, path="/t/messages.js"):
    return {
        "type": "Timeout",
        "rule_id": rule_id,
        "path": path,
        "level": "warn",
        "message": f"Timeout when running {rule_id} on {path}",
    }


def test_pack_rule_timeout_distrusts_the_file():
    """정책 조건이 끝나지 않았으면 그 파일의 '거짓'을 믿을 수 없다. 보수적으로 간다."""
    res = parse_semgrep_json({"results": [], "errors": [_timeout("kr.network-act.50-3.night-ad.send-call")]})
    assert res.hard_unparsed == {Path("/t/messages.js")}


def test_timeouts_at_the_threshold_distrust_the_file():
    """시간 초과가 세 번 나면 semgrep 이 나머지 규칙을 오류 없이 건너뛴다(실측). 함수 경계 규칙의 시간 초과는
    하나로는 파일을 믿지 않을 까닭이 아니지만, 문턱에 닿으면 정책 조건도 건너뛰었다."""
    errs = [_timeout("policypack-region.typescript")] * 3
    res = parse_semgrep_json({"results": [], "errors": errs})
    assert res.hard_unparsed == {Path("/t/messages.js")}


# ── 규칙 id 를 컴파일한 id 로 되돌린다 ─────────────────────────────────────────────

KINDS_CONFIG = {
    "rules": [
        {
            "id": "kr.p.r.pred",
            "metadata": {"policypack": {"policy": "kr.p", "rule": "r", "group": "g", "predicate": "p"}},
        },
        {"id": "policypack-region.typescript", "metadata": {"policypack_region": {"lang": "typescript"}}},
    ]
}
PRED = PredicateKey("kr.p", "r", "g", "p")


def _table():
    from policypack.static.parse import rule_table

    return rule_table(KINDS_CONFIG)


def test_a_prefixed_pack_timeout_resolves_to_its_predicate():
    """semgrep 은 규칙 id 앞에 설정 폴더 경로를 붙인다(TMPDIR=/Users/dev/x → 'Users.dev.x.'). 규칙 표로
    되돌려야 그 조건만 '모름'으로 둔다."""
    res = parse_semgrep_json({"results": [], "errors": [_timeout("Users.dev.x.kr.p.r.pred")]}, _table())
    assert res.rule_timeouts == {Path("/t/messages.js"): ["kr.p.r.pred"]}
    assert res.predicate_timeouts == {Path("/t/messages.js"): [PRED]}
    assert res.hard_unparsed == set() and res.incomplete == set()


def test_a_prefixed_region_timeout_resolves_to_its_id():
    res = parse_semgrep_json(
        {"results": [], "errors": [_timeout("private.tmp.x.policypack-region.typescript")]}, _table()
    )
    assert res.rule_timeouts == {Path("/t/messages.js"): ["policypack-region.typescript"]}
    assert res.predicate_timeouts == {} and res.incomplete == set() and res.hard_unparsed == set()


def test_an_unknown_rule_timeout_leaves_the_whole_file_unfinished():
    res = parse_semgrep_json({"results": [], "errors": [_timeout("tmp.something-else")]}, _table())
    assert res.incomplete == {Path("/t/messages.js")}


def test_timeouts_at_the_threshold_leave_the_whole_file_unfinished():
    errs = [_timeout("policypack-region.typescript")] * 3
    res = parse_semgrep_json({"results": [], "errors": errs}, _table())
    assert res.incomplete == {Path("/t/messages.js")}


@pytest.mark.parametrize("label", ["Too many matches", "Stack overflow", "Fixpoint timeout", "Internal matching error"])
def test_other_rule_level_errors_leave_their_predicate_unfinished(label):
    err = {**_timeout("tmp.kr.p.r.pred"), "type": label}
    res = parse_semgrep_json({"results": [], "errors": [err]}, _table())
    assert res.predicate_timeouts == {Path("/t/messages.js"): [PRED]} and res.rule_errors == []


def test_semgrep_prefixes_rule_ids_with_the_config_folder(tmp_path, monkeypatch):
    """되돌리기가 기대는 사실을 실제 semgrep 으로 확인한다: 규칙 id 앞에 설정 파일이 든 폴더 경로가 붙는다."""
    import tempfile

    from policypack.static.parse import canonical_rule_id, rule_table
    from policypack.static.semgrep_cli import SemgrepBackend

    tmp = tmp_path / "cfg"
    tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp))
    target = tmp_path / "a.js"
    target.write_text("send(user.phone);\n", encoding="utf-8")
    config = {
        "rules": [
            {
                "id": "kr.p.r.pred",
                "languages": ["javascript"],
                "severity": "INFO",
                "message": "m",
                "pattern": "send(...)",
                "metadata": {"policypack": {"policy": "kr.p", "rule": "r", "group": "g", "predicate": "p"}},
            }
        ]
    }
    data, _ = SemgrepBackend().raw(config, [target])
    check_id = data["results"][0]["check_id"]
    assert check_id.endswith(".cfg.kr.p.r.pred")
    assert canonical_rule_id(check_id, rule_table(config)) == "kr.p.r.pred"


def test_rule_ids_that_end_with_another_id_are_refused():
    """한 id 가 다른 id 의 점 경계 접미사면, 임시 폴더 이름에 따라 어느 규칙의 시간 초과인지 가를 수 없다."""
    from policypack.errors import PackError
    from policypack.static.compile import check_rule_ids

    with pytest.raises(PackError, match="로 끝납니다"):
        check_rule_ids([{"id": "p.r.pred"}, {"id": "kr.p.r.pred"}])
    with pytest.raises(PackError, match="겹칩니다"):
        check_rule_ids([{"id": "a.b"}, {"id": "a.b"}])
    check_rule_ids([{"id": "kr.p.r.pred"}, {"id": "kr.p.r.pred.generic"}, {"id": "policypack-region.typescript"}])


# ── 어느 파일인지 모르는 파일 단위 오류 ───────────────────────────────────────


@pytest.mark.parametrize("label", ["Out of memory", "Stack overflow", "Fatal error", "Other syntax error"])
def test_a_file_level_error_without_a_path_is_kept_not_dropped(label):
    err = {"type": label, "level": "error", "message": "no path"}
    res = parse_semgrep_json({"results": [], "errors": [err]})
    assert res.unlocated_errors and label in res.unlocated_errors[0]
    assert res.rule_errors == []


def test_rule_errors_without_a_path_still_stop_the_scan():
    err = {"type": "Rule parse error", "level": "error", "message": "bad pattern"}
    assert parse_semgrep_json({"results": [], "errors": [err]}).rule_errors


def test_the_backend_leaves_every_target_of_a_run_with_an_unlocated_error_unfinished(monkeypatch, tmp_path):
    """버리면 그 실행의 어느 파일이든 '모름'이 조용히 '거짓'이 된다. 파싱 실패로 두면 정규식 조건은 여전히
    '거짓'이라 적용 조건이 정규식인 규칙이 흔적 없이 꺼졌다(검토에서 실측). 끝나지 않은 것으로 둔다."""
    from policypack.static.semgrep_cli import SemgrepBackend

    a, b = tmp_path / "a.js", tmp_path / "b.js"
    backend = SemgrepBackend()
    data = {"version": "1.176.1", "results": [], "errors": [{"type": "Timeout", "level": "error", "message": "t"}]}
    monkeypatch.setattr(backend, "raw", lambda config, targets: (data, 0.1))
    res = backend.run({"rules": []}, [a, b])
    assert res.incomplete == {a, b} and res.hard_unparsed == set()
    assert res.engine == "semgrep 1.176.1" and res.runs == 1


def test_chunked_runs_report_the_same_engine_version_and_count_runs(monkeypatch, tmp_path):
    from policypack.static.semgrep_cli import SemgrepBackend

    files = [tmp_path / f"{i}.js" for i in range(3)]
    backend = SemgrepBackend()
    data = {"version": "1.176.1", "results": [], "errors": []}
    monkeypatch.setattr(backend, "raw", lambda config, targets: (data, 0.1))
    single = backend.run({"rules": []}, files)
    monkeypatch.setattr(backend, "CHUNK", 1)
    chunked = backend.run({"rules": []}, files)
    assert chunked.backend_version == single.backend_version == "1.176.1"
    assert (single.runs, chunked.runs) == (1, 3)
