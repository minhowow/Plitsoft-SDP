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


def test_masking_keeps_the_line_count():
    key = "-----BEGIN RSA PRIVATE KEY-----\nMIIE\nabcd\n-----END RSA PRIVATE KEY-----\nnext()"
    out, counts = mask(key)
    assert counts == {"private-key": 1} and out.count("\n") == key.count("\n") and out.endswith("next()")


def test_tools_mask_the_whole_file_before_cutting(tmp_path):
    """읽는 구간만 가리면 개인키 블록의 중간부터 읽을 때 본문이 그대로 나갔다. 검색 결과에 BEGIN 줄이 있으면 그 뒤의
    검색 결과가 모두 지워졌다."""
    (tmp_path / "keys.ts").write_text(
        "export const pem = `\n-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n"
        "-----END PRIVATE KEY-----`;\nexport const other = 1;\n",
        encoding="utf-8",
    )
    (tmp_path / "z.ts").write_text("export const target = 2;\n", encoding="utf-8")
    t = RepoTools(tmp_path)
    out = t.call("read_file", {"path": "keys.ts", "start_line": 3})
    assert "MIIE" not in out and "5\texport const other = 1;" in out
    hits = t.search("export|BEGIN")
    assert "MIIE" not in hits and "z.ts:1: export const target = 2;" in hits and "keys.ts:5:" in hits
    assert t.masked == {"private-key": 1}  # 중간부터 읽은 구간에는 가린 자리 표시도 본문도 없다


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
    # 전송 기록(R26): 검색 결과로 줄이 나간 파일, 목록으로 나간 이름 수, 읽기를 거절한 비밀 파일
    assert t.matched == [".env.example"] and t.refused == [".env"]
    names = t.call("list_files", {"path": "src"})
    assert t.listed == len(names.splitlines()) == 4


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
    cut = '{"results": [{"entry": "a.ts", "verdict": "충족", "citations": [{"file": "a.ts"}]}, {"entry": "b.ts", "verd'
    assert parse(cut) == {
        "results": [{"entry": "a.ts", "verdict": "충족", "citations": [{"file": "a.ts"}]}],
        "partial": True,
    }


def test_agent_stops_asking_once_the_service_is_unreachable(repo):
    """연달아 두 질문이 서비스에 닿지 못하면 남은 질문은 보내지 않는다. 그 요청만 거절된 것(400)은 세지 않는다."""
    from policypack.judge.http import Unavailable

    tries = []

    def down(body):
        tries.append(1)
        raise Unavailable("연결 실패: refused")

    judge = AgentJudge("m", down)
    answers = [judge.ask(Q, repo) for _ in range(4)]
    assert len(tries) == 2 and judge.skipped == 2
    assert [a.failure for a in answers[2:]] == ["transport: skipped"] * 2

    def refused(body):
        tries.append(1)
        raise RuntimeError("HTTP 400: prompt is too long")

    judge = AgentJudge("m", refused)
    assert all(judge.ask(Q, repo).failure.startswith("transport: HTTP 400") for _ in range(3)) and judge.skipped == 0

    flaky = iter([Unavailable("x"), None, Unavailable("x"), None])

    def sometimes(body):
        err = next(flaky)
        if err:
            raise err
        return {"content": answer(), "usage": {}}

    judge = AgentJudge("m", sometimes)
    [judge.ask(Q, repo) for _ in range(4)]
    assert judge.skipped == 0  # 사이에 답이 오면 다시 센다


def test_agent_stops_at_its_deadline(repo):
    """마감이 지나면 새 질문은 보내지 않고, 대화 중인 질문은 다음 차례를 보내지 않는다(웹 쪽 요청 R10)."""
    import time

    sent = []

    def slow(body):
        sent.append(1)
        return {"content": [tool("list_files")], "usage": {}}

    judge = AgentJudge("m", slow)
    judge.deadline = time.monotonic() - 1
    a = judge.ask(Q, repo)
    assert a.failure == "time: skipped" and sent == [] and judge.skip_reasons == {"time": 1}

    judge = AgentJudge("m", slow)
    judge.deadline = time.monotonic() + 0.05

    def tick(body):
        time.sleep(0.06)
        return slow(body)

    judge.transport = tick
    a = judge.ask(Q, repo)
    assert a.failure == "time" and len(sent) == 1


def test_build_needs_key():
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build("anthropic:m", env={})
    with pytest.raises(ValueError, match="알 수 없습니다"):
        build("openai:m", env={"ANTHROPIC_API_KEY": "k"})
    assert build("anthropic:claude-x", env={"ANTHROPIC_API_KEY": "k"}).id == "agent:anthropic:claude-x"
    # 별칭을 풀어 부른다. 풀지 않으면 API 가 모델을 몰라 질문이 모두 실패했다(R7)
    assert build("anthropic:haiku", env={"ANTHROPIC_API_KEY": "k"}).model == "claude-haiku-5-5"


def test_gate_puts_the_citation_on_the_line_where_it_is(repo):
    """줄 번호는 모델이 적은 값이다. 웹은 그 줄로 링크를 만든다(R25). 관문을 통과한 인용은 실제 줄로 맞추고, 다르면
    모델의 값을 line_model 에 남긴다. 맞으면 그대로 둔다. 통과하지 못한 인용은 손대지 않는다."""
    [wrong, right, multi, none, made_up] = gate(
        repo,
        [
            {"file": "src/components/AgeGate.tsx", "line": 1, "text": "if (age < 14) throw new Error"},
            {"file": "src/components/AgeGate.tsx", "line": 3, "text": "if (age < 14) throw new Error"},
            {"file": "src/pages/Signup.tsx", "line": 9, "text": "export default function Signup() { return (<form>"},
            {"file": "src/components/AgeGate.tsx", "text": "if (age < 14) throw new Error"},
            {"file": "src/components/AgeGate.tsx", "line": 7, "text": "if (age < 19) throw"},
        ],
    )
    assert (wrong["line"], wrong["line_model"]) == (3, 1)
    assert right["line"] == 3 and "line_model" not in right
    assert (multi["line"], multi["line_model"]) == (2, 9)  # 두 줄에 걸친 인용은 시작 줄
    assert (none["line"], none["line_model"]) == (3, None)
    assert not made_up["ok"] and made_up["line"] == 7 and "line_model" not in made_up


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
        ("src/pages/Signup.tsx", "해당 없음", [AGE]),  # 해당 없음은 진입 파일의 줄이어야 한다
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


SIGNUP_LINE = {
    "file": "src/pages/Signup.tsx",
    "line": 3,
    "text": "return (<form><input name='birth' /><AgeGate /></form>)",
}


def test_independent_makes_findings_from_agent_answers(repo):
    (repo / "docs").mkdir()
    (repo / "docs" / "ai.md").write_text("# 챗봇 사용법\nGPT 로 답한다\n", encoding="utf-8")
    pack, duties = load_pack(KR_CORE), load_duties(KR_CORE)
    send = scripted(
        *[answer() for _ in range(3)],
        answer(
            ("src/pages/Signup.tsx", "미충족", [SIGNUP_LINE], 3),
            ("src/ghost.tsx", "미충족", []),
            ("src/pages/Signup.tsx", "모름", [SIGNUP_LINE]),
            ("docs/ai.md", "미충족", [{"file": "docs/ai.md", "line": 2, "text": "GPT 로 답한다"}]),
            ("src/chat/Chat.tsx", "미충족", []),
            ("src/components/AgeGate.tsx", "미충족", [SIGNUP_LINE]),
        ),
    )
    files = sorted(repo.rglob("*.tsx"))
    findings, rec = run_independent(repo, pack, duties, AgentJudge("m", send), files)
    order = [p.id for p in pack.policies]
    assert [q["policy"] for q in rec["questions"]] == order and rec["mode"] == "independent"
    assert "스스로 찾고" in prompt_text(send) and "이미 본 곳" not in prompt_text(send)
    assert [(f.policy, f.rule, f.outcome, f.line) for f in findings] == [
        (order[3], "agent-independent", Outcome.NEEDS_REVIEW, 3)
    ]
    # 모델이 적은 줄(3)이 인용이 실제로 있는 줄과 같아서 그대로다
    assert all("line_model" not in f.agent for f in findings)
    assert rec["actions"] == {
        "warned": 1,
        "dropped-no-file": 1,
        "dropped-duplicate": 1,
        "dropped-out-of-scope": 1,
        "dropped-ungrounded": 2,  # 인용 없음 · 다른 파일의 줄만 인용
    }
    assert rec["model_calls"] == len(order) and rec["usage"]["input_tokens"] == 10 * len(order)  # 정책마다 질문 하나


def test_a_warning_lands_on_the_cited_line_not_the_claimed_one(repo):
    """독립 검토가 낸 경고의 줄도 모델이 적은 값이다. 진입 파일에서 통과한 인용의 줄이 아니면 그 줄로 맞춘다(R25)."""
    pack, duties = load_pack(KR_CORE), load_duties(KR_CORE)
    send = scripted(answer(("src/pages/Signup.tsx", "미충족", [{**SIGNUP_LINE, "line": 1}], 40)))
    findings, rec = run_independent(repo, pack, duties, AgentJudge("m", send), sorted(repo.rglob("*.tsx")))
    [f] = findings
    assert f.line == SIGNUP_LINE["line"] and f.agent["line_model"] == 40
    assert f.agent["citations"][0]["line_model"] == 1


def test_discovery_skips_what_static_already_saw(repo):
    pack, duties = load_pack(KR_CORE), load_duties(KR_CORE)
    send = scripted(answer(("src/pages/Signup.tsx", "미충족", [SIGNUP_LINE])))
    findings, rec = run_independent(
        repo,
        pack,
        duties,
        AgentJudge("m", send),
        known={"kr.pipa.22-2": ["src/pages/Signup.tsx"]},
        rule="agent-discovered",
    )
    assert findings == [] and rec["actions"] == {"dropped-known": 1} and rec["mode"] == "discover"
    assert "이미 본 곳" in prompt_text(send) and "`src/pages/Signup.tsx`" in prompt_text(send)
    assert rec["questions"][0]["known"] == 1 and rec["questions"][1]["known"] == 0


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
    assert "https://api.anthropic.com/v1/messages 로 나갑니다" in out.err.replace("\n", "")
    assert doc["run"]["agent"]["actions"] == {"confirmed": 1}
    assert all(f["agent"]["action"] == "confirmed" and f["outcome"] == "needs-review" for f in doc["findings"])
    assert [f["rule"] for f in doc["findings"]] == [f["rule"] for f in plain["findings"]]

    cite = [{"file": "signup.ts", "line": 3, "text": "await prisma.user.create({ data: { email: body.email"}]
    monkeypatch.setattr(
        agent_mod, "build", fake(scripted(*[answer() for _ in range(4)], answer(("signup.ts", "미충족", cite, 3))))
    )
    args = ["scan", str(target), "--agent", "anthropic:fake", "--output-format", "json", "--exit-zero"]
    assert main([*args, "--agent-mode", "independent"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["run"]["agent"]["mode"] == "independent" and doc["run"]["engine"] is None
    assert [(f["rule"], f["line"]) for f in doc["findings"]] == [("agent-independent", 3)]

    # combined: review 한 번(22-2 의 경고 단위), 그다음 정책마다 찾기. 22-2 의 찾기는 이미 본 signup.ts 를 다시 답해도
    # 버리고, 31-1 의 찾기가 새로 찾은 파일만 다시 확인(recheck)한 뒤 경고로 더한다
    (target / "chat.ts").write_text("export const reply = await openai.chat.completions.create({ model })\n")
    chat = [
        {"file": "chat.ts", "line": 1, "text": "export const reply = await openai.chat.completions.create({ model })"}
    ]
    send = scripted(
        answer(("signup.ts", "미충족", [])),
        answer(("signup.ts", "미충족", cite, 3)),
        answer(),
        answer(),
        answer(("chat.ts", "미충족", chat, 1)),
        answer(),
        answer(),
        answer(("chat.ts", "미충족", [])),  # 찾은 곳을 review 처럼 다시 묻는다
    )
    monkeypatch.setattr(agent_mod, "build", fake(send))
    assert main([*args, "--agent-mode", "combined"]) == 0
    doc = json.loads(capsys.readouterr().out)
    agent = doc["run"]["agent"]
    assert agent["mode"] == "combined" and agent["discover"]["mode"] == "discover"
    assert agent["discover"]["actions"] == {"dropped-known": 1, "warned": 1}
    assert agent["recheck"]["actions"] == {"confirmed": 1}
    calls = agent["model_calls"] + agent["discover"]["model_calls"] + agent["recheck"]["model_calls"]
    assert agent["total_model_calls"] == calls == 8
    assert [(Path(f["file"]).name, f["policy"]) for f in doc["findings"] if f["rule"] == "agent-discovered"] == [
        ("chat.ts", "kr.ai-basic-act.31-1")
    ]


def test_time_limit_flag_keeps_the_static_result(tmp_path, monkeypatch, capsys):
    import shutil

    import policypack.judge.agent as agent_mod
    from policypack.cli import main

    target = tmp_path / "app"
    target.mkdir()
    shutil.copy(KR_CORE / "tests" / "pipa-22-2" / "violating.ts", target / "signup.ts")
    sent = []

    def never(body):
        sent.append(1)
        return {"content": answer(), "usage": {}}

    monkeypatch.setattr(agent_mod, "build", lambda spec, budget=20, env=None: AgentJudge("m", never, budget=budget))
    base = ["scan", str(target), "--output-format", "json", "--agent", "anthropic:m"]
    assert main([*base, "--agent-time-limit", "0"]) == 2
    assert "0 보다 커야" in capsys.readouterr().err
    import itertools
    import time

    # 시계: 에이전트 단계 시작 0초(마감 1초), 첫 질문 직전 10초(마감이 지남), 끝 15초
    monkeypatch.setattr(time, "monotonic", itertools.chain([0.0, 10.0], itertools.repeat(15.0)).__next__)
    assert main([*base, "--agent-time-limit", "1"]) == 1
    out = capsys.readouterr()
    agent = json.loads(out.out)["run"]["agent"]
    assert sent == [] and agent["skipped_reasons"] == {"time": 1} and agent["seconds"] == 15.0
    assert "시간 상한" in out.err


@pytest.mark.parametrize("mode", ["review", "combined", "independent"])
def test_an_unreachable_agent_leaves_the_static_result(tmp_path, monkeypatch, capsys, mode):
    """네트워크가 끊겨도 정적 판정은 그대로 남고, 보내지 않은 질문을 알린다. 독립 검토는 정적 판정이 없으므로
    본 것이 없다 — 경고가 없어도 '검토할 것 없음'(0)으로 끝내지 않는다."""
    import shutil

    import policypack.judge.agent as agent_mod
    from policypack.cli import main
    from policypack.judge.http import Unavailable

    target = tmp_path / "app"
    target.mkdir()
    shutil.copy(KR_CORE / "tests" / "pipa-22-2" / "violating.ts", target / "signup.ts")
    shutil.copy(KR_CORE / "tests" / "pipa-28-8" / "openai-profile-summary.ts", target / "summary.ts")
    shutil.copy(KR_CORE / "tests" / "network-act-50-3" / "violating.ts", target / "ads.ts")
    base = ["scan", str(target), "--output-format", "json"]
    plain_code = main(base)
    plain = json.loads(capsys.readouterr().out)
    sent = []

    def down(body):
        sent.append(1)
        raise Unavailable("연결 실패: refused")

    monkeypatch.setattr(agent_mod, "build", lambda spec, budget=20, env=None: AgentJudge("fake", down, budget=budget))
    code = main([*base, "--agent", "anthropic:fake", "--agent-mode", mode])
    out = capsys.readouterr()
    doc = json.loads(out.out)
    agent = doc["run"]["agent"]
    assert len(sent) == AgentJudge.GIVE_UP_AFTER and agent["questions_skipped"] > 0 and "보내지 않았습니다" in out.err
    if mode == "independent":
        assert doc["findings"] == [] and agent["unanswered"] == len(agent["questions"]) > 0
        assert code == 1
        assert main([*base, "--agent", "anthropic:fake", "--agent-mode", mode, "--fail-on", "review"]) == 0
        capsys.readouterr()
    else:
        key = lambda f: (f["policy"], f["rule"], f["file"], f["line"], f["outcome"])  # noqa: E731
        assert sorted(map(key, doc["findings"])) == sorted(map(key, plain["findings"])) and code == plain_code == 1
        assert {f["agent"]["action"] for f in doc["findings"]} == {"kept-no-answer"}
        assert agent["unanswered"] > 0


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

    # 재확인 단계가 푼 경고도 글과 SARIF 에 실린다(R20)
    result.agent["recheck"] = {
        "records": [{**result.agent["records"][0], "entry": "src/chat/Chat.tsx", "policy": "kr.ai-basic-act.31"}]
    }
    out = text.render(result, repo, explain=True, color=False)
    assert "src/chat/Chat.tsx  kr.ai-basic-act.31  → 충족 (찾은 곳 재확인)" in out
    cleared = sarif.build(result, load_pack(KR_CORE), KR_CORE, repo)["runs"][0]["invocations"][0]["properties"]
    assert [(c["stage"], c["entry"]) for c in cleared["agent"]["cleared"]] == [
        ("review", "src/pages/Signup.tsx"),
        ("recheck", "src/chat/Chat.tsx"),
    ]

    plain = EvalResult(findings=[_finding(repo, "kr.pipa.22-2", "src/pages/Signup.tsx")])
    assert "에이전트" not in text.render(plain, repo, explain=True, color=False)
    assert (
        "agent" not in sarif.build(plain, load_pack(KR_CORE), KR_CORE, repo)["runs"][0]["invocations"][0]["properties"]
    )


def test_recheck_model_flag(tmp_path, monkeypatch, capsys):
    import shutil

    import policypack.judge.agent as agent_mod
    from policypack.cli import main

    target = tmp_path / "app"
    target.mkdir()
    shutil.copy(KR_CORE / "tests" / "pipa-22-2" / "violating.ts", target / "signup.ts")
    built = []

    def fake(spec, budget=20, env=None):
        built.append(spec)
        return AgentJudge(spec, scripted(), budget=budget)

    monkeypatch.setattr(agent_mod, "build", fake)
    base = ["scan", str(target), "--agent", "anthropic:a", "--output-format", "json", "--exit-zero"]
    assert main([*base, "--agent-recheck", "anthropic:b"]) == 2  # combined 에서만
    capsys.readouterr()
    assert main([*base, "--agent-mode", "combined", "--agent-recheck", "anthropic:b"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert built == ["anthropic:a", "anthropic:b"] and "recheck_total_usage" in doc["run"]["agent"]
