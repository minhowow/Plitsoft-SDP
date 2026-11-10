"""CI·편집기 연동: GitLab Code Quality 출력과 Claude Code 훅."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from policypack.cli import main
from policypack.integrations import claude_code

REPO = Path(__file__).resolve().parents[1]
FIX = "policies/kr-core/tests"
VIOLATING = f"{FIX}/pipa-22-2/violating.ts"
COMPLIANT = f"{FIX}/pipa-22-2/under14-branch.ts"


@pytest.fixture(autouse=True)
def _in_repo(monkeypatch):
    monkeypatch.chdir(REPO)


# ── GitLab Code Quality ─────────────────────────────────────────────────────


def _gitlab(capsys, *args) -> list[dict]:
    main(["scan", *args, "--output-format", "gitlab"])
    return json.loads(capsys.readouterr().out)


def test_gitlab_report_shape(capsys):
    issues = _gitlab(capsys, f"{FIX}/pipa-22-2")
    assert issues
    for i in issues:
        assert set(i) == {"description", "check_name", "fingerprint", "severity", "location"}
        assert i["severity"] in {"major", "minor"}
        assert i["location"]["lines"]["begin"] >= 1
        # 저장소 루트에서의 상대 경로라야 GitLab 이 머지 요청의 줄을 찾는다
        assert i["location"]["path"].startswith(f"{FIX}/pipa-22-2/")
    v = [i for i in issues if i["location"]["path"] == VIOLATING]
    assert v and v[0]["check_name"].startswith("kr.pipa.22-2/") and "제22조의2" in v[0]["description"]
    assert len({i["fingerprint"] for i in issues}) == len(issues)


def test_gitlab_fingerprint_matches_sarif(capsys):
    issues = _gitlab(capsys, VIOLATING)
    main(["scan", VIOLATING, "--output-format", "sarif"])
    sarif = json.loads(capsys.readouterr().out)
    fps = {next(iter(r["partialFingerprints"].values())) for r in sarif["runs"][0]["results"]}
    assert {i["fingerprint"] for i in issues} == fps


def test_gitlab_empty_report_is_an_empty_list(capsys, tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    assert _gitlab(capsys, str(tmp_path)) == []


# ── Claude Code 훅 ──────────────────────────────────────────────────────────


def _payload(path, tool="Edit", cwd=REPO) -> str:
    return json.dumps({"tool_name": tool, "tool_input": {"file_path": str(path)}, "cwd": str(cwd)})


def test_hook_reports_a_needs_review_file_to_claude(capsys):
    assert claude_code.run(_payload(VIOLATING), None, main) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "block"
    assert "violating.ts" in out["reason"] and "제22조의2" in out["reason"]


def test_hook_is_quiet_on_a_compliant_file(capsys):
    assert claude_code.run(_payload(REPO / COMPLIANT), None, main) == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "payload",
    [
        _payload(VIOLATING, tool="Read"),
        _payload("README.md"),
        _payload("없는/파일.ts"),
        json.dumps({"tool_name": "Write", "tool_input": {}}),
        "[]",
    ],
)
def test_hook_ignores_what_it_should_not_scan(payload, capsys):
    calls = []
    assert claude_code.run(payload, None, lambda argv: calls.append(argv) or 1) == 0
    assert calls == [] and capsys.readouterr().out == ""


def test_hook_skips_generated_dirs(tmp_path, capsys):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    dep = tmp_path / "node_modules/x/index.ts"
    dep.parent.mkdir(parents=True)
    dep.write_text((REPO / VIOLATING).read_text(encoding="utf-8"), encoding="utf-8")
    calls = []
    assert claude_code.run(_payload(dep, cwd=tmp_path), None, lambda argv: calls.append(argv) or 1) == 0
    assert calls == []


def test_hook_only_blocks_on_certain_findings_and_never_calls_ai():
    """'불확실'만으로는 끼어들지 않는다(--fail-on review). 판정자·에이전트를 켜지 않는다."""
    seen = []
    claude_code.run(_payload(VIOLATING), "my-pack", lambda argv: seen.append(argv) or 0)
    (argv,) = seen
    assert argv[argv.index("--fail-on") + 1] == "review"
    assert argv[argv.index("--config") + 1] == "my-pack"
    assert "--judge" not in argv and "--agent" not in argv


def test_hook_tool_error_is_not_a_block(capsys):
    assert claude_code.run(_payload(VIOLATING), None, lambda argv: 2) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "검사하지 못했습니다" in captured.err


def test_hook_rejects_non_json(capsys):
    assert claude_code.run("not json", None, main) == 1


def test_hook_command_reads_stdin(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload(VIOLATING)))
    assert main(["hook", "claude-code"]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "block"
