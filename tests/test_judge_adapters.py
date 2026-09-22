"""판정자 어댑터 — 모델을 부르지 않고 시험한다.

실제 호출은 사용자의 구독 사용량을 쓰므로 테스트에 넣지 않는다. 대신 **격리와
프롬프트 동일성**을 고정한다. 격리가 깨지면 판정자가 프롬프트 밖을 보고, 두 어댑터의
프롬프트가 다르면 판정자를 바꿀 때 답이 조용히 달라진다.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from policypack.cli import main
from policypack.judge import claude_cli
from policypack.judge.base import SYSTEM, Question, json_only, parse_answer
from policypack.judge.claude_cli import ISOLATION_FLAGS, ISOLATION_SHA, ClaudeCliJudge, build_command

REPO = Path(__file__).resolve().parents[1]

Q = Question(
    text="이 코드에 만 14세 미만 사용자의 가입을 막거나 법정대리인 동의를 확인하는 처리가 있는가?",
    code="\nexport async function signUp(dto) {\n  return userRepo.save(dto);\n}\n",
    lang="typescript",
)


# ── 격리 ────────────────────────────────────────────────────────────────────


def test_isolation_flags_are_pinned():
    """이 목록에서 하나라도 빠지면 판정자가 프롬프트 밖을 본다.

    2026-09-19 에 --allowedTools "" 만으로는 판정자가 작업 폴더의 파일을 읽었다.
    해시를 박아 두어 실수로 완화되면 테스트가 깨지게 한다.
    """
    assert ISOLATION_SHA == "ab42ecc9de758bc1", (
        f"격리 플래그가 바뀌었습니다. 의도한 변경이면 해시를 갱신하세요. 현재: {ISOLATION_SHA}"
    )


@pytest.mark.parametrize(
    "flag",
    [
        "--restricted",
        "--strict-mcp-config",
        "--setting-sources",
        "--max-turns",
        "--permission-prompts",
        "--disallowedTools",
    ],
)
def test_every_isolation_switch_is_present(flag):
    assert flag in build_command("haiku")


@pytest.mark.parametrize("tool", ["Read", "Bash", "WebFetch", "Task", "Skill"])
def test_tools_are_denied_by_name(tool):
    """도구를 이름으로 명시해 막는다. --restricted 만으로는 부족했다."""
    assert tool in ISOLATION_FLAGS


def test_max_turns_is_one():
    cmd = build_command("haiku")
    assert cmd[cmd.index("--max-turns") + 1] == "1"


def test_settings_are_not_inherited():
    """--setting-sources "" 를 넣기 전에는 판정자 입력이 최대 2.4만 토큰이었다."""
    cmd = build_command("haiku")
    assert cmd[cmd.index("--setting-sources") + 1] == ""
    assert cmd[cmd.index("--mcp-config") + 1] == '{"mcpServers":{}}'


# ── CLI 응답 해석 (모델 호출 없음) ──────────────────────────────────────────


def _fake_run(payload: dict | str, returncode: int = 0):
    def run(cmd, **kw):
        out = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.CompletedProcess(cmd, returncode, stdout=out, stderr="")

    return run


GOOD = {
    "result": '{"answer": "예", "evidence": "return userRepo.save(dto);"}',
    "num_turns": 1,
    "total_cost_usd": 0.0031,
}


def test_good_answer(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(GOOD))
    a = ClaudeCliJudge("haiku").ask(Q)
    assert a.raw == "예" and a.failure is None
    assert a.evidence == "return userRepo.save(dto);"


def test_multi_turn_answer_is_discarded(monkeypatch):
    """도구를 쓰려 했다는 뜻이다. 프롬프트만 보고 한 답이 아니므로 쓰지 않는다."""
    monkeypatch.setattr(subprocess, "run", _fake_run({**GOOD, "num_turns": 3}))
    a = ClaudeCliJudge("haiku").ask(Q)
    assert a.raw == "?" and a.failure == "isolation"


def test_permission_denial_is_discarded(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run({**GOOD, "permission_denials": [{"tool": "Read"}]}))
    assert ClaudeCliJudge("haiku").ask(Q).failure == "isolation"


def test_cli_error_is_transport(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run({"is_error": True, "result": "rate limited", "num_turns": 1}))
    a = ClaudeCliJudge("haiku").ask(Q)
    assert a.failure == "transport"


def test_non_json_output_is_parse_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run("이건 JSON 이 아닙니다"))
    assert ClaudeCliJudge("haiku").ask(Q).failure == "parse"


def test_failure_is_never_raised_as_an_exception(monkeypatch):
    """시제품은 RuntimeError 를 던졌다. 이제는 Answer.failure 로 내린다. 그 AI 조건은 판정에 넣지 않고
    'AI 확인 필요'로 보고된다."""
    monkeypatch.setattr(subprocess, "run", _fake_run({**GOOD, "num_turns": 9}))
    a = ClaudeCliJudge("haiku").ask(Q)
    assert a.raw == "?"


def test_neutral_working_directory(monkeypatch):
    """폴더 이름으로도 프로젝트를 추론하지 못하게 빈 임시 폴더에서 돈다."""
    seen = {}

    def run(cmd, **kw):
        seen["cwd"] = kw.get("cwd")
        seen["env"] = kw.get("env")
        seen["stdin"] = kw.get("input")
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(GOOD), stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    ClaudeCliJudge("haiku").ask(Q)
    cwd = Path(seen["cwd"])
    assert cwd.name.startswith("judge-")
    assert not list(cwd.iterdir()) if cwd.exists() else True
    assert seen["env"]["MAX_THINKING_TOKENS"] == "0", "사고 과정 없이 답한다"
    assert seen["stdin"] == Q.prompt(), "프롬프트는 stdin 으로 준다"


# ── 응답 파싱 ───────────────────────────────────────────────────────────────


def test_json_followed_by_prose_is_parsed():
    """판정자는 JSON 뒤에 설명을 덧붙이곤 한다. 그 설명 때문에 답을 버리면 '모름'이 경고로 남는다."""
    raw = '{"answer": "아니오", "evidence": ""}\n\n설명: 보호자 동의 처리가 보이지 않습니다.'
    assert parse_answer(raw) == ("아니오", "", False)


def test_fenced_json_is_parsed():
    assert parse_answer('```json\n{"answer":"예","evidence":"abc"}\n```')[0] == "예"


def test_nested_braces_survive():
    raw = '{"answer":"예","evidence":"if (a) { b(); }"}'
    assert json_only(raw) == raw


def test_explanation_first_then_json_is_parsed():
    """함수 구역 방식 시범(2026-09-27)의 파싱 실패 7건은 모두 설명과 코드 블록을 먼저 썼다.
    첫 '{' 가 코드의 중괄호라 답을 잃었다. 끝에 붙인 답은 읽는다."""
    raw = (
        "코드를 분석하겠습니다.\n\n```javascript\n(function (w, d) {\n  j.src = x + i;\n})(window, document);\n```\n\n"
        '결론:\n{"answer": "예", "evidence": "if (a) { return; }"}'
    )
    assert parse_answer(raw) == ("예", "if (a) { return; }", False)
    reordered = '설명 { 코드 }\n{"evidence": "x = 1;", "answer": "아니오"}'
    assert parse_answer(reordered) == ("아니오", "x = 1;", False)


def test_explanation_without_an_answer_still_fails():
    raw = "코드를 분석하겠습니다.\n```js\nfunction f() { return 1; }\n```\n판단하기 어렵습니다."
    assert parse_answer(raw) == ("?", "", True)


def test_the_first_answer_wins_over_later_ones():
    raw = '{"answer": "아니오", "evidence": ""}\n예를 들어 {"answer": "예"} 라고 답하면 틀린다.'
    assert parse_answer(raw) == ("아니오", "", False)


@pytest.mark.parametrize("word,expected", [("yes", "예"), ("No", "아니오"), ("해당없음", "해당없음"), ("maybe", "?")])
def test_answer_normalization(word, expected):
    assert parse_answer(json.dumps({"answer": word}))[0] == expected


# ── 고르기 ──────────────────────────────────────────────────────────────────


def test_build_dispatch():
    from policypack.judge.anthropic_api import AnthropicApiJudge, build

    assert isinstance(build("claude-cli:sonnet").inner, ClaudeCliJudge)
    assert build("claude-cli:sonnet").id == "claude-cli:sonnet"
    assert isinstance(build("anthropic:haiku").inner, AnthropicApiJudge)
    with pytest.raises(ValueError):
        build("openai:gpt")


def test_api_judge_without_a_key_fails_softly(monkeypatch):
    """키가 없다고 터지면 안 된다. 판정 하나가 '모름'이 될 뿐이다."""
    from policypack.judge.anthropic_api import AnthropicApiJudge

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    a = AnthropicApiJudge("haiku").ask(Q)
    assert a.raw == "?" and a.failure == "transport"


def test_both_adapters_send_the_same_prompt():
    """어느 어댑터를 쓰든 판정자가 받는 지시가 같아야 한다."""
    from policypack.judge.anthropic_api import AnthropicApiJudge

    assert ClaudeCliJudge("haiku").system == AnthropicApiJudge("haiku").system == SYSTEM


def test_available_reports_whether_the_cli_is_installed():
    assert isinstance(claude_cli.available(), bool)


# ── 한 실행 안의 중복 질문 · 깨진 답 ─────────────────────────────────────────


def test_broken_json_in_the_answer_is_a_parse_failure(monkeypatch):
    """답 JSON 의 따옴표가 깨져 있으면 파싱 실패다. 판정에 넣지 않고 'AI 확인 필요'로 남는다."""
    bad = {"result": '{"answer": "예", "evidence": "<a href="x">"}', "num_turns": 1, "total_cost_usd": 0.01}
    monkeypatch.setattr(subprocess, "run", _fake_run(bad))
    a = ClaudeCliJudge("haiku").ask(Q)
    assert a.failure == "parse"


def test_a_run_never_asks_the_same_question_twice(tmp_path, monkeypatch, capsys):
    """같은 질문·같은 코드는 한 실행에서 한 번만 묻는다. 가짜 claude CLI 가 불린 횟수를 센다."""
    log = tmp_path / "calls.log"
    fake = tmp_path / "fake_claude"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "sys.stdin.read()\n"
        "open(os.environ['FAKE_CLAUDE_LOG'], 'a').write('x\\n')\n"
        "print(json.dumps({'is_error': False, 'num_turns': 1, 'total_cost_usd': 0,\n"
        "                  'result': json.dumps({'answer': '아니오', 'evidence': ''})}))\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    import policypack.judge.claude_cli as claude_cli

    monkeypatch.setattr(claude_cli, "BIN", str(fake))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    src = (REPO / "policies/kr-core/tests/pipa-22-2/violating.ts").read_text(encoding="utf-8")
    for name in ("a.ts", "b.ts"):
        (tmp_path / name).write_text(src, encoding="utf-8")
    code = main(
        [
            "scan",
            str(tmp_path / "a.ts"),
            str(tmp_path / "b.ts"),
            "--judge",
            "claude-cli:haiku",
            "--no-color",
            "--output-format",
            "json",
        ]
    )
    doc = json.loads(capsys.readouterr().out)
    assert code == 1 and len(doc["findings"]) == 2
    assert log.read_text().count("x") == 1, "같은 (질문, 코드)를 두 번 물었다"
