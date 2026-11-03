"""에이전트형 판정기와 에이전트 검토 단계. 모델을 부르지 않는다(가짜 전송)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from policypack.evaluate.agent_pass import gate, run_agent_pass
from policypack.evaluate.engine import EvalResult
from policypack.judge.agent import AgentJudge, AgentQuestion, RepoTools, build, parse
from policypack.pack.loader import load_duties, load_pack
from policypack.report.outcome import Finding, Outcome

REPO = Path(__file__).resolve().parents[1]
KR_CORE = REPO / "policies" / "kr-core"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    files = {
        "src/pages/Signup.tsx": (
            "import { AgeGate } from '../components/AgeGate'\n"
            "export default function Signup() {\n"
            "  return (<form><input name='birth' /><AgeGate /></form>)\n"
            "}\n"
        ),
        "src/components/AgeGate.tsx": (
            "export const AgeGate = () => {\n"
            "  // 만 14세 미만 차단\n"
            "  if (age < 14) throw new Error('만 14세 미만은 가입할 수 없습니다')\n"
            "  return null\n"
            "}\n"
        ),
        "src/chat/Chat.tsx": "export const Chat = () => <div>{answer}</div>\n",
    }
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    return root


def scripted(*turns):
    """turns: 응답 content 목록. 요청 본문은 sent 에 쌓인다."""
    sent = []
    queue = list(turns)

    def send(body):
        sent.append(body)
        content = queue.pop(0) if queue else [{"type": "text", "text": "{}"}]
        return {"content": content, "usage": {"input_tokens": 10, "output_tokens": 3}}

    send.sent = sent
    return send


def answer(verdict, citations=(), reason="r"):
    doc = {"verdict": verdict, "citations": list(citations), "reason": reason}
    return [{"type": "text", "text": json.dumps(doc, ensure_ascii=False)}]


def tool(name, **inp):
    return {"type": "tool_use", "id": f"t-{name}-{len(inp)}", "name": name, "input": inp}


Q = AgentQuestion(
    policy="kr.pipa.22-2", title="아동", duties=({"id": "pipa-22-2-1", "duty_ko": "d"},), entry="src/pages/Signup.tsx"
)


def test_tools_stay_inside(repo):
    t = RepoTools(repo)
    assert "저장소 밖" in t.call("read_file", {"path": "../secret.txt"})
    assert "outside" not in t.search("outside")
    assert t.call("read_file", {"path": "src/chat/Chat.tsx"}).startswith("1\texport const Chat")
    assert "도구 오류" in t.call("read_file", {})


def test_judge_reads_then_answers(repo):
    send = scripted(
        [tool("read_file", path="src/components/AgeGate.tsx")],
        answer("충족", [{"file": "src/components/AgeGate.tsx", "line": 3, "text": "if (age < 14) throw"}]),
    )
    ans = AgentJudge("m", send, budget=5).ask(Q, repo)
    assert ans.verdict == "compliant" and ans.tool_calls == 1 and ans.failure is None
    tool_result = send.sent[1]["messages"][-1]["content"][0]
    assert "만 14세 미만 차단" in tool_result["content"]
    assert send.sent[0]["messages"][0]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "pipa-22-2-1" in send.sent[0]["messages"][0]["content"][0]["text"]


def test_budget_turns_tools_off(repo):
    turns = [[tool("search", pattern="x")] for _ in range(3)] + [answer("모름")]
    send = scripted(*turns)
    ans = AgentJudge("m", send, budget=2).ask(Q, repo)
    assert [b["tool_choice"]["type"] for b in send.sent] == ["auto", "auto", "none", "none"]
    assert ans.verdict == "unknown" and ans.tool_calls == 3


def test_parse_failure_and_transport_failure(repo):
    assert AgentJudge("m", scripted([{"type": "text", "text": "몰라요"}])).ask(Q, repo).failure == "parse"

    def broken(body):
        raise RuntimeError("HTTP 500")

    assert AgentJudge("m", broken).ask(Q, repo).failure.startswith("transport")
    assert parse('앞 {"x": "{"} {"verdict": "충족"}') == {"verdict": "충족"}


def test_build_needs_key():
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build("anthropic:m", env={})
    with pytest.raises(ValueError, match="알 수 없습니다"):
        build("openai:m", env={"ANTHROPIC_API_KEY": "k"})
    assert build("anthropic:claude-x", env={"ANTHROPIC_API_KEY": "k"}).id == "agent:anthropic:claude-x"


def test_gate_multi_file(repo):
    res = gate(
        repo,
        [
            {"file": "src/components/AgeGate.tsx", "line": 3, "text": "if (age < 14) throw new Error"},
            {"file": "src/components/AgeGate.tsx", "line": 2, "text": "// 만 14세 미만 차단"},
            {"file": "../secret.txt", "line": 1, "text": "outside"},
            {"file": "src/nope.ts", "line": 1, "text": "whatever code"},
            {"file": "src/chat/Chat.tsx", "line": 1, "text": "지어낸 줄 const x = 1"},
        ],
    )
    assert [(r["ok"], r["why"]) for r in res] == [
        (True, "grounded"),
        (False, "comment-only"),
        (False, "outside-repo"),
        (False, "no-such-file"),
        (False, "not-found"),
    ]


def _result(repo: Path, outcome=Outcome.NEEDS_REVIEW_UNCERTAIN) -> EvalResult:
    f1 = Finding(policy="kr.pipa.22-2", rule="a", outcome=outcome, file=str(repo / "src/pages/Signup.tsx"), line=3)
    f2 = Finding(policy="kr.ai-basic-act.31", rule="b", outcome=outcome, file=str(repo / "src/chat/Chat.tsx"), line=1)
    return EvalResult(findings=[f1, f2])


def _files(repo: Path) -> list[Path]:
    return sorted(p for p in repo.rglob("*.tsx"))


def test_pass_clears_only_with_grounded_citation_and_confirms_raises(repo):
    pack, duties = load_pack(KR_CORE), load_duties(KR_CORE)
    send = scripted(
        answer("미충족", [{"file": "src/chat/Chat.tsx", "line": 1, "text": "<div>{answer}</div>"}]),
        answer("충족", [{"file": "src/components/AgeGate.tsx", "line": 3, "text": "if (age < 14) throw"}]),
    )
    result = _result(repo)
    rec = run_agent_pass(result, repo, pack, duties, AgentJudge("m", send), _files(repo))
    assert [(f.policy, f.outcome) for f in result.findings] == [("kr.ai-basic-act.31", Outcome.NEEDS_REVIEW)]
    assert result.findings[0].agent["action"] == "confirmed"
    assert rec["actions"] == {"confirmed": 1, "cleared": 1}
    cleared = next(r for r in rec["records"] if r["action"] == "cleared")
    assert cleared["entry"] == "src/pages/Signup.tsx"
    assert {"file": "src/components/AgeGate.tsx", "why": "imports"} in cleared["related"]
    assert cleared["findings"] == [{"rule": "a", "line": 3, "outcome": Outcome.NEEDS_REVIEW_UNCERTAIN.value}]
    # 의무 설명이 질문에 실린다
    assert "법정대리인" in send.sent[1]["messages"][0]["content"][0]["text"]


@pytest.mark.parametrize(
    "verdict,cites",
    [
        ("충족", []),
        ("충족", [{"file": "src/components/AgeGate.tsx", "line": 2, "text": "// 만 14세 미만 차단"}]),
        ("해당 없음", [{"file": "src/pages/Signup.tsx", "line": 1, "text": "지어낸 import 줄입니다"}]),
        ("모름", []),
    ],
)
def test_pass_keeps_warning_without_grounded_citation(repo, verdict, cites):
    pack, duties = load_pack(KR_CORE), load_duties(KR_CORE)
    send = scripted(answer("모름"), answer(verdict, cites))
    result = _result(repo)
    run_agent_pass(result, repo, pack, duties, AgentJudge("m", send), _files(repo))
    assert len(result.findings) == 2
    assert all(f.outcome is Outcome.NEEDS_REVIEW_UNCERTAIN for f in result.findings)


def test_pass_respects_max_units(repo):
    pack, duties = load_pack(KR_CORE), load_duties(KR_CORE)
    send = scripted(answer("미충족"))
    result = _result(repo)
    rec = run_agent_pass(result, repo, pack, duties, AgentJudge("m", send), _files(repo), max_units=1)
    assert rec["asked"] == 1 and rec["units"] == 2 and len(send.sent) == 1
    assert sum(1 for f in result.findings if f.agent) == 1


def test_scan_with_agent_adds_records_and_none_stays_plain(tmp_path, monkeypatch, capsys):
    """--agent 를 주면 run.agent 와 findings[].agent 가 붙는다. 주지 않으면 보고서에 agent 키가 없다."""
    import shutil

    import policypack.judge.agent as agent_mod
    from policypack.cli import main

    target = tmp_path / "app"
    target.mkdir()
    shutil.copy(KR_CORE / "tests" / "pipa-22-2" / "violating.ts", target / "signup.ts")

    assert main(["scan", str(target), "--output-format", "json", "--exit-zero"]) == 0
    plain = json.loads(capsys.readouterr().out)
    assert plain["findings"] and "agent" not in plain["run"]
    assert all("agent" not in f for f in plain["findings"])

    send = scripted(answer("미충족", [{"file": "signup.ts", "line": 1, "text": "x"}]))
    monkeypatch.setattr(agent_mod, "build", lambda spec, budget=20, env=None: AgentJudge("fake", send, budget=budget))
    assert main(["scan", str(target), "--agent", "anthropic:fake", "--output-format", "json", "--exit-zero"]) == 0
    out = capsys.readouterr()
    doc = json.loads(out.out)
    assert "Anthropic API 로 나갑니다" in out.err
    assert doc["run"]["agent"]["actions"] == {"confirmed": 1}
    assert doc["run"]["agent"]["records"][0]["entry"] == "signup.ts"
    assert all(f["agent"]["action"] == "confirmed" and f["outcome"] == "needs-review" for f in doc["findings"])
    assert [f["rule"] for f in doc["findings"]] == [f["rule"] for f in plain["findings"]]
