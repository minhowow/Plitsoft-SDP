"""에이전트형 판정기, 외부 전송 통제, 에이전트 검토 단계. 모델을 부르지 않는다(가짜 전송)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import policypack.evaluate.agent_pass as agent_pass
from policypack.egress import is_secret_file, mask
from policypack.evaluate.agent_pass import gate, run_agent_pass, run_independent
from policypack.evaluate.engine import EvalResult
from policypack.judge.agent import AgentJudge, AgentQuestion, Entry, RepoTools, build, parse
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
        "src/config.ts": "export const apiKey = 'sk-proj-abcdefghijklmnopqrstuvwxyz123456'\n",
        ".env": "OPENAI_API_KEY=sk-live-should-never-leave-1234567890\n",
        ".env.example": "OPENAI_API_KEY=\n",
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


def answer(*results):
    """results: (entry, verdict, citations[, line])"""
    docs = []
    for r in results:
        d = {"entry": r[0], "verdict": r[1], "citations": list(r[2]), "reason": "r"}
        if len(r) > 3:
            d["line"] = r[3]
        docs.append(d)
    return [{"type": "text", "text": json.dumps({"results": docs}, ensure_ascii=False)}]


def tool(name, **inp):
    return {"type": "tool_use", "id": f"t-{name}-{len(inp)}", "name": name, "input": inp}


def prompt_text(send, i=0) -> str:
    return send.sent[i]["messages"][0]["content"][0]["text"]


Q = AgentQuestion(
    policy="kr.pipa.22-2",
    title="아동",
    duties=({"id": "pipa-22-2-1", "duty_ko": "d"},),
    entries=(Entry("src/pages/Signup.tsx"),),
)
AGE = {"file": "src/components/AgeGate.tsx", "line": 3, "text": "if (age < 14) throw"}
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"


# ── 외부 전송 통제 ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("const k = 'AKIAABCDEFGHIJKLMNOP'", "aws-key"),
        ("token: ghp_abcdefghijklmnopqrstuvwxyz0123456789", "github-token"),
        ("ANTHROPIC = 'sk-ant-api03-abcdefghijklmnopqrstuvwx'", "api-key"),
        ("key=AIzaSyA1234567890abcdefghijklmnopqrstuv", "google-key"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----", "private-key"),
        (f"Bearer {JWT}", "jwt"),
        ("const password = 'hunter2hunter2'", "secret-value"),
        ("주민번호 900101-1234567 입력", "rrn"),
        ("card 4111 1111 1111 1111", "card"),
    ],
)
def test_mask_kinds(text, kind):
    out, counts = mask(text)
    assert counts.get(kind) == 1 and "[가림:" in out


@pytest.mark.parametrize(
    "text",
    [
        "문의: 02-1234-5678, help@example.com",  # 광고 전송자 연락처는 이행 근거다. 가리지 않는다
        "const password = process.env.DB_PASSWORD",
        "const token = ''",
        "order 1234 5678 9012 3456",  # Luhn 실패
        "Date.now() === 1712345678901",
    ],
)
def test_mask_leaves_evidence_alone(text):
    assert mask(text) == (text, {})


def test_secret_files():
    assert is_secret_file(".env") and is_secret_file("apps/web/.env.local") and is_secret_file("certs/server.pem")
    assert not is_secret_file(".env.example") and not is_secret_file("src/env.ts") and not is_secret_file("key.ts")


def test_tools_stay_inside_and_mask(repo):
    t = RepoTools(repo)
    assert "저장소 밖" in t.call("read_file", {"path": "../secret.txt"})
    assert "outside" not in t.search("outside")
    assert "읽지 않는다" in t.call("read_file", {"path": ".env"})
    assert "should-never-leave" not in t.search("OPENAI")
    assert "OPENAI_API_KEY=" in t.search("OPENAI")  # .env.example 은 읽는다
    assert "[가림:api-key]" in t.call("read_file", {"path": "src/config.ts"})
    assert t.masked == {"api-key": 1}
    assert t.read == ["src/config.ts"]
    assert "도구 오류" in t.call("read_file", {})


# ── 판정기 ────────────────────────────────────────────────────────────


def test_judge_reads_then_answers(repo):
    send = scripted(
        [tool("read_file", path="src/components/AgeGate.tsx")],
        answer(("src/pages/Signup.tsx", "충족", [AGE])),
    )
    ans = AgentJudge("m", send, budget=5).ask(Q, repo)
    res = ans.for_entry("src/pages/Signup.tsx")
    assert res.verdict == "compliant" and ans.tool_calls == 1 and ans.failure is None
    assert "만 14세 미만 차단" in send.sent[1]["messages"][-1]["content"][0]["content"]
    assert send.sent[0]["messages"][0]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "pipa-22-2-1" in prompt_text(send)
    assert ans.read_files == ["src/components/AgeGate.tsx"]


def test_budget_turns_tools_off_and_scales_with_entries(repo):
    send = scripted(*([[tool("search", pattern="x")]] * 3), answer())
    ans = AgentJudge("m", send, budget=2).ask(Q, repo)
    assert [b["tool_choice"]["type"] for b in send.sent] == ["auto", "auto", "none", "none"]
    assert ans.results == [] and ans.tool_calls == 3
    j = AgentJudge("m", send, budget=20)
    many = AgentQuestion(policy="p", title="t", duties=(), entries=tuple(Entry(f"f{i}") for i in range(6)))
    assert j.budget_for(Q) == 20 and j.budget_for(many) == 40
    assert j.budget_for(AgentQuestion(policy="p", title="t", duties=(), mode="independent")) == 40


def test_parse_failure_and_transport_failure(repo):
    ans = AgentJudge("m", scripted([{"type": "text", "text": "몰라요"}])).ask(Q, repo)
    assert ans.failure == "parse" and ans.raw == "몰라요"

    def broken(body):
        raise RuntimeError("HTTP 500")

    assert AgentJudge("m", broken).ask(Q, repo).failure.startswith("transport")
    assert parse('앞 {"x": "{"} {"results": []}') == {"results": []}
    assert parse('{"verdict": "충족"}') is None


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


# ── review (M4) ───────────────────────────────────────────────────────


def _finding(repo: Path, policy: str, rel: str, rule: str = "a") -> Finding:
    return Finding(policy=policy, rule=rule, outcome=Outcome.NEEDS_REVIEW_UNCERTAIN, file=str(repo / rel), line=1)


def _result(repo: Path) -> EvalResult:
    return EvalResult(
        findings=[
            _finding(repo, "kr.pipa.22-2", "src/pages/Signup.tsx"),
            _finding(repo, "kr.ai-basic-act.31", "src/chat/Chat.tsx", "b"),
        ]
    )


def _run(repo, send, result=None, **kw):
    result = result or _result(repo)
    files = sorted(p for p in repo.rglob("*.ts*"))
    judge = AgentJudge("m", send)
    rec = run_agent_pass(result, repo, load_pack(KR_CORE), load_duties(KR_CORE), judge, files, **kw)
    return result, rec


def test_pass_clears_only_with_grounded_citation_and_confirms_raises(repo):
    send = scripted(
        answer(("src/chat/Chat.tsx", "미충족", [])),
        answer(("src/pages/Signup.tsx", "충족", [AGE])),
    )
    result, rec = _run(repo, send)
    assert [(f.policy, f.outcome) for f in result.findings] == [("kr.ai-basic-act.31", Outcome.NEEDS_REVIEW)]
    assert result.findings[0].agent["action"] == "confirmed"
    assert rec["actions"] == {"confirmed": 1, "cleared": 1} and rec["mode"] == "review"
    cleared = next(r for r in rec["records"] if r["action"] == "cleared")
    assert {"file": "src/components/AgeGate.tsx", "why": "imports"} in cleared["related"]
    assert cleared["findings"] == [{"rule": "a", "line": 1, "outcome": Outcome.NEEDS_REVIEW_UNCERTAIN.value}]
    assert "법정대리인" in prompt_text(send, 1)
    assert [q["policy"] for q in rec["questions"]] == ["kr.ai-basic-act.31", "kr.pipa.22-2"]


COMMENT = {"file": "src/components/AgeGate.tsx", "line": 2, "text": "// 만 14세 미만 차단"}
MADE_UP = {"file": "src/pages/Signup.tsx", "line": 1, "text": "지어낸 import 줄입니다"}


@pytest.mark.parametrize(
    "res",
    [
        ("src/pages/Signup.tsx", "충족", []),
        ("src/pages/Signup.tsx", "충족", [COMMENT]),
        ("src/pages/Signup.tsx", "해당 없음", [MADE_UP]),
        ("src/pages/Signup.tsx", "모름", []),
        ("src/other.tsx", "충족", [AGE]),  # 묻지 않은 파일에 대한 답은 쓰지 않는다
    ],
)
def test_pass_keeps_warning_without_grounded_answer(repo, res):
    result, _ = _run(repo, scripted(answer(), answer(res)))
    assert len(result.findings) == 2
    assert all(f.outcome is Outcome.NEEDS_REVIEW_UNCERTAIN for f in result.findings)


def test_same_policy_entries_share_one_question(repo):
    (repo / "src/pages/Join.tsx").write_text("export default () => <form><input name='birth'/></form>\n")
    pages = ("src/pages/Signup.tsx", "src/pages/Join.tsx")
    send = scripted(answer(("src/pages/Join.tsx", "미충족", []), ("src/pages/Signup.tsx", "충족", [AGE])))
    result, rec = _run(repo, send, EvalResult(findings=[_finding(repo, "kr.pipa.22-2", p) for p in pages]))
    assert len(send.sent) == 1
    assert rec["questions"][0]["entries"] == ["src/pages/Join.tsx", "src/pages/Signup.tsx"]
    assert [(Path(f.file).name, f.outcome) for f in result.findings] == [("Join.tsx", Outcome.NEEDS_REVIEW)]


def test_later_chunks_get_earlier_evidence(repo, monkeypatch):
    (repo / "src/pages/Join.tsx").write_text("export default () => <form><input name='birth'/></form>\n")
    pages = ("src/pages/Signup.tsx", "src/pages/Join.tsx")
    monkeypatch.setattr(agent_pass, "CHUNK", 1)
    send = scripted(
        answer(("src/pages/Join.tsx", "충족", [AGE])),
        answer(("src/pages/Signup.tsx", "충족", [AGE])),
    )
    result, rec = _run(repo, send, EvalResult(findings=[_finding(repo, "kr.pipa.22-2", p) for p in pages]))
    assert result.findings == [] and len(send.sent) == 2
    assert "앞서 같은 정책을 볼 때 이행 근거로 확인된 줄" in prompt_text(send, 1)
    assert "if (age < 14) throw" in prompt_text(send, 1)
    assert [q["carried"] for q in rec["questions"]] == [0, 1]


def test_pass_respects_max_units(repo):
    send = scripted(answer(("src/chat/Chat.tsx", "미충족", [])))
    result, rec = _run(repo, send, max_units=1)
    assert rec["asked"] == 1 and rec["units"] == 2 and len(send.sent) == 1
    assert sum(1 for f in result.findings if f.agent) == 1


def test_parse_failure_keeps_everything_and_records_raw(repo):
    send = scripted([{"type": "text", "text": "형식이 틀린 답"}], [{"type": "text", "text": "또"}])
    result, rec = _run(repo, send)
    assert len(result.findings) == 2 and rec["actions"] == {"kept-no-answer": 2}
    assert rec["questions"][0]["raw"] == "형식이 틀린 답"


# ── independent (M3) ──────────────────────────────────────────────────


def test_independent_makes_findings_from_agent_answers(repo):
    pack, duties = load_pack(KR_CORE), load_duties(KR_CORE)
    send = scripted(
        *[answer() for _ in range(3)],
        answer(
            ("src/pages/Signup.tsx", "미충족", [], 3),
            ("src/ghost.tsx", "미충족", []),
            ("src/pages/Signup.tsx", "모름", []),
        ),
    )
    findings, rec = run_independent(repo, pack, duties, AgentJudge("m", send))
    order = [p.id for p in pack.policies]
    assert [q["policy"] for q in rec["questions"]] == order
    assert "스스로 찾고" in prompt_text(send)
    assert [(f.policy, f.rule, f.outcome, f.line) for f in findings] == [
        (order[3], "agent-independent", Outcome.NEEDS_REVIEW, 3)
    ]
    assert rec["actions"] == {"warned": 1, "dropped-no-file": 1, "dropped-duplicate": 1}


# ── CLI ───────────────────────────────────────────────────────────────


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

    def fake(send):
        return lambda spec, budget=20, env=None: AgentJudge("fake", send, budget=budget)

    monkeypatch.setattr(agent_mod, "build", fake(scripted(answer(("signup.ts", "미충족", [])))))
    assert main(["scan", str(target), "--agent", "anthropic:fake", "--output-format", "json", "--exit-zero"]) == 0
    out = capsys.readouterr()
    doc = json.loads(out.out)
    assert "Anthropic API 로 나갑니다" in out.err.replace("\n", "")
    assert doc["run"]["agent"]["actions"] == {"confirmed": 1}
    assert all(f["agent"]["action"] == "confirmed" and f["outcome"] == "needs-review" for f in doc["findings"])
    assert [f["rule"] for f in doc["findings"]] == [f["rule"] for f in plain["findings"]]

    monkeypatch.setattr(
        agent_mod, "build", fake(scripted(*[answer() for _ in range(4)], answer(("signup.ts", "미충족", [], 2))))
    )
    args = ["scan", str(target), "--agent", "anthropic:fake", "--agent-mode", "independent", "--output-format", "json"]
    assert main([*args, "--exit-zero"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["run"]["agent"]["mode"] == "independent" and doc["run"]["engine"] is None
    assert [(f["rule"], f["line"]) for f in doc["findings"]] == [("agent-independent", 2)]


def test_text_and_sarif_show_agent_results(repo):
    from policypack.report import sarif, text

    send = scripted(
        answer(
            ("src/chat/Chat.tsx", "미충족", [{"file": "src/chat/Chat.tsx", "line": 1, "text": "<div>{answer}</div>"}])
        ),
        answer(("src/pages/Signup.tsx", "충족", [AGE])),
    )
    result, _ = _run(repo, send)
    result.agent = _run(repo, scripted(answer(), answer()))[1] | {"actions": {"confirmed": 1, "cleared": 1}}
    result.agent["records"] = [
        {
            "action": "cleared",
            "entry": "src/pages/Signup.tsx",
            "policy": "kr.pipa.22-2",
            "verdict": "compliant",
            "reason": "나이 차단",
            "citations": gate(repo, [AGE]),
        }
    ]
    out = text.render(result, repo, explain=True, color=False)
    assert "에이전트  미충족" in out and "src/chat/Chat.tsx:1 “<div>{answer}</div>”" in out
    assert "에이전트가 해제한 경고" in out and "src/components/AgeGate.tsx:3 “if (age < 14) throw”" in out
    assert "에이전트 검토(review)" in out and "confirmed 1" in out

    doc = sarif.build(result, load_pack(KR_CORE), KR_CORE, repo)
    run = doc["runs"][0]
    assert run["invocations"][0]["properties"]["agent"]["cleared"][0]["entry"] == "src/pages/Signup.tsx"
    res = run["results"][0]
    assert res["properties"]["agent"]["verdict"] == "not-compliant"
    assert res["relatedLocations"][-1]["message"]["text"] == "에이전트가 인용한 줄"

    plain = EvalResult(findings=[_finding(repo, "kr.pipa.22-2", "src/pages/Signup.tsx")])
    assert "에이전트" not in text.render(plain, repo, explain=True, color=False)
    assert (
        "agent" not in sarif.build(plain, load_pack(KR_CORE), KR_CORE, repo)["runs"][0]["invocations"][0]["properties"]
    )
