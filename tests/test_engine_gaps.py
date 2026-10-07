"""엔진이 끝내지 못한 곳을 '거짓'으로 읽지 않는다.

엔진 출력에 오류를 끼워 넣어 재현한다(실제 semgrep 은 그대로 돌고, 결과만 바꾼다).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from policypack.cli import main
from policypack.static.semgrep_cli import SemgrepBackend

REPO = Path(__file__).resolve().parents[1]
CASE = "policies/kr-core/tests/pipa-22-2/violating.ts"
PREDICATE = "birth-or-age"  # 정규식 조건이다(파싱과 무관 → generic 사본이 있다)


@pytest.fixture(autouse=True)
def _in_repo(monkeypatch):
    monkeypatch.chdir(REPO)


def _inject(monkeypatch, errors_for):
    """semgrep 결과에서 PREDICATE 매치를 지우고 errors_for(config, targets) 가 주는 오류를 더한다."""
    original = SemgrepBackend.raw

    def raw(self, config, targets):
        data, elapsed = original(self, config, targets)
        data["results"] = [
            r
            for r in data["results"]
            if (r.get("extra", {}).get("metadata", {}).get("policypack") or {}).get("predicate") != PREDICATE
        ]
        data.setdefault("errors", []).extend(errors_for(config, targets))
        return data, elapsed

    monkeypatch.setattr(SemgrepBackend, "raw", raw)


def _scan_json(capsys, *extra) -> tuple[dict, str]:
    main(["scan", CASE, "--output-format", "json", "--no-color", *extra])
    out, err = capsys.readouterr()
    return json.loads(out), err


def _child_findings(doc: dict) -> list[dict]:
    return [f for f in doc["findings"] if f["policy"] == "kr.pipa.22-2" and f["file"].endswith("violating.ts")]


def test_control_the_child_consent_warning_is_found(capsys):
    doc, _ = _scan_json(capsys)
    assert [f["outcome"] for f in _child_findings(doc)] == ["needs-review"]


def test_a_timeout_without_a_path_keeps_the_warning_as_uncertain(monkeypatch, capsys):
    """경로 없는 오류로 대상을 '파싱 실패'로만 두면 정규식 조건은 여전히 '거짓'이라 경고가 흔적 없이
    사라졌다(검토에서 실측: '만 14세' 경고 0건). 이제 모든 조건이 '모름'이고 경고는 불확실로 남는다."""
    _inject(monkeypatch, lambda config, targets: [{"type": "Timeout", "level": "error", "message": "t"}])
    doc, err = _scan_json(capsys)
    found = _child_findings(doc)
    assert [(f["outcome"], f["untested_reasons"][0]) for f in found] == [
        ("needs-review-uncertain", "engine-incomplete")
    ]
    assert doc["run"]["engine_errors"] and doc["run"]["incomplete"]
    assert doc["run"]["coverage_complete"] is False
    assert "어느 파일인지 밝히지 않은 오류" in err


def test_a_timeout_on_the_regex_copy_keeps_only_that_condition_unknown(monkeypatch, capsys):
    """경로와 규칙 id 가 붙은 시간 초과는 그 조건만 '모름'으로 둔다. 정규식 사본이 끝나지 않았는데
    '매치 없음'을 믿으면 적용 조건이 거짓이 되어 규칙이 꺼진다."""

    def errors(config, targets):
        rid = next(r["id"] for r in config["rules"] if r["id"].endswith(f".{PREDICATE}.generic"))
        path = next(str(t) for t in targets if str(t).endswith("violating.ts"))
        return [{"type": "Timeout", "level": "warn", "rule_id": "var.folders.x.T." + rid, "path": path}]

    _inject(monkeypatch, errors)
    doc, _ = _scan_json(capsys)
    assert [(f["outcome"], f["untested_reasons"][0]) for f in _child_findings(doc)] == [
        ("needs-review-uncertain", "engine-incomplete")
    ]
    assert doc["run"]["engine_errors"] == [] and any(p.endswith("violating.ts") for p in doc["run"]["incomplete"])


def test_sarif_names_engine_errors_and_unfinished_files(monkeypatch, capsys):
    _inject(monkeypatch, lambda config, targets: [{"type": "Out of memory", "level": "error", "message": "OOM"}])
    main(["scan", CASE, "--output-format", "sarif", "--no-color"])
    notes = json.loads(capsys.readouterr().out)["runs"][0]["invocations"][0]["toolExecutionNotifications"]
    kinds = {n["descriptor"]["id"] for n in notes}
    assert {"policypack/engine-error", "policypack/engine-incomplete"} <= kinds
    assert "policypack/unparsed" not in kinds  # 파일 문법 문제로 적지 않는다
    engine_error = next(n for n in notes if n["descriptor"]["id"] == "policypack/engine-error")
    assert "locations" not in engine_error and "OOM" in engine_error["message"]["text"]


def test_policypack_test_says_why_everything_failed(monkeypatch, capsys):
    """경로 없는 오류 하나로 픽스처가 대량 실패해도 원인이 어디에도 없어 규칙 회귀로 오인했다(검토에서 실측)."""
    _inject(monkeypatch, lambda config, targets: [{"type": "Timeout", "level": "error", "message": "t"}])
    main(["test", "--exit-zero", "--no-color"])
    out, err = capsys.readouterr()
    assert "엔진 오류 1건" in out and "경고:" in err
    main(["test", "--exit-zero", "--output-format", "json"])
    run = json.loads(capsys.readouterr().out)["run"]
    # 함수 단위 규칙이 있으면 함수 경계를 구하는 두 번째 실행이 더 있을 수 있다
    assert run["engine_errors"] and run["engine_runs"] >= 1


@pytest.mark.skipif(os.name == "nt", reason="chmod 000 은 POSIX 에서만 읽기를 막는다")
def test_an_unreadable_file_is_skipped_not_fatal(tmp_path, capsys):
    """semgrep 은 읽을 수 없는 대상이 하나라도 있으면 출력 없이 끝난다. 검사 전체가 실패했다(검토에서 실측)."""
    ok = tmp_path / "ok.ts"
    ok.write_text("export const a = 1;\n", encoding="utf-8")
    locked = tmp_path / "locked.ts"
    locked.write_text("export const b = 2;\n", encoding="utf-8")
    locked.chmod(0)
    try:
        if os.access(locked, os.R_OK):
            pytest.skip("이 계정은 권한과 상관없이 읽을 수 있다(root)")
        code = main(["scan", str(tmp_path), "--output-format", "json", "--no-color"])
        out, err = capsys.readouterr()
        assert code in (0, 1)
        assert any(p.endswith("locked.ts") for p in json.loads(out)["run"]["skipped"])
        assert "읽을 권한이 없는 파일" in err
    finally:
        locked.chmod(0o644)
