"""policypack review: 이해 → 의무별 근거 찾기 → 반박을 가짜 답으로 끝까지 돌린다. 모델 호출 0회."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from policypack import review as rv
from policypack.judge.agent import AgentJudge

jsonschema = pytest.importorskip("jsonschema")
SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "review-1.json").read_text(encoding="utf-8"))

FILES = {
    "package.json": json.dumps({"dependencies": {"express": "^4.0.0"}}),
    "src/routes/signup.ts": (
        'import express from "express";\n'
        "const router = express.Router();\n"
        'router.post("/signup", async (req, res) => {\n'
        "  const { email, name, birthDate } = req.body;\n"
        "  await db.user.create({ data: { email, name, birthDate } });\n"
        "  res.json({ ok: true });\n"
        "});\n"
    ),
    "server/answer.py": (
        "from openai import OpenAI\n"
        "client = OpenAI()\n"
        "def answer(name, question):\n"
        '    return client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": name}])\n'
    ),
    "src/pages/Privacy.tsx": "export default function Privacy() {\n  return <h1>개인정보 처리방침</h1>;\n}\n",
    "tests/signup.test.ts": 'it("signs up", () => {\n  expect(signup({ birthDate: "2015-01-01" })).toBe(true);\n});\n',
}


def _repo(tmp_path: Path) -> Path:
    for name, text in FILES.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def _text(body: dict) -> str:
    c = body["messages"][0]["content"]
    return c if isinstance(c, str) else c[0]["text"]


def _reply(doc: dict) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(doc, ensure_ascii=False)}],
        "usage": {"input_tokens": 1000, "output_tokens": 200},
    }


SIGNUP = {"file": "src/routes/signup.ts", "line": 4, "text": "const { email, name, birthDate } = req.body;"}
STORE = {
    "file": "src/routes/signup.ts",
    "line": 9,
    "text": "await db.user.create({ data: { email, name, birthDate } })",
}
OPENAI = {"file": "server/answer.py", "line": 4, "text": "return client.chat.completions.create("}
FAKE = {"file": "src/routes/signup.ts", "line": 2, "text": "verifyGuardianConsent(birthDate)"}
TEST_LINE = {"file": "tests/signup.test.ts", "line": 2, "text": 'expect(signup({ birthDate: "2015-01-01" }))'}


def _node(nid: str, kind: str, label: str, cite: dict) -> dict:
    return {"id": nid, "kind": kind, "label": label, "data": ["생년월일"], "citations": [cite]}


def fake_investigator():
    """첫 의무: 충족(인용이 시험 파일 → 확인할 것), 둘째: 해당 없음(지어낸 인용 → 확인할 것), 셋째: 확인할 것,
    그 밖: 충족(관문 통과). 이해 단계는 신호가 못 본 AI 기능과 개인정보 흐름을 낸다. 첫 답 앞에 도구를 한 번 쓴다."""
    seen: set[str] = set()

    def send(body: dict) -> dict:
        prompt = _text(body)
        if prompt.startswith("이 저장소가 어떤 서비스인지"):
            return _reply(
                {
                    "summary": "회원 가입을 받고 AI 답변을 주는 서비스다.",
                    "features_added": [
                        {"feature": "genai", "citations": [OPENAI], "reason": "Python 서버가 OpenAI 를 부른다"},
                        {"feature": "location", "citations": [FAKE], "reason": "지어낸 인용"},
                    ],
                    "features_removed": [{"feature": "auth", "citations": [], "reason": "인용 없음"}],
                    "flow": {
                        "nodes": [
                            _node("n1", "input", "가입 폼", SIGNUP),
                            _node("n2", "store", "DB", STORE),
                            _node("n3", "external", "OpenAI", OPENAI),
                            _node("n4", "external", "가짜", FAKE),
                        ],
                        "edges": [
                            {"from": "n1", "to": "n2", "data": ["생년월일"], "citations": [STORE]},
                            {"from": "n1", "to": "n4", "data": [], "citations": [STORE]},
                        ],
                    },
                }
            )
        ids = re.findall(r"^- \[([^\]]+)\]", prompt, re.M)
        key = ",".join(ids)
        if key not in seen and body["tool_choice"]["type"] != "none":
            seen.add(key)
            tool = {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "src/routes/signup.ts"}}
            return {"content": [tool], "usage": {"input_tokens": 500, "output_tokens": 20}}
        results = []
        for i, d in enumerate(ids):
            status, cites = ["충족 근거 있음", "해당 없음", "확인할 것", "충족 근거 있음"][min(i, 3)], [STORE]
            cites = [TEST_LINE] if i == 0 else [FAKE] if i == 1 else cites
            results.append({"duty": d, "status": status, "citations": cites, "question": "어디서?", "reason": "r"})
        return _reply({"results": results})

    return send


def fake_checker(send_log: list):
    """'확인할 것'은 뒤집어 충족(관문 통과)으로, 충족 근거 있음은 유지한다."""

    def send(body: dict) -> dict:
        prompt = _text(body)
        send_log.append(prompt)
        out = []
        for block in re.split(r"^(?=- \[)", prompt, flags=re.M)[1:]:
            d = re.match(r"- \[([^\]]+)\]", block).group(1)
            if "앞 판단: 확인할 것" in block:
                flip = {"result": "뒤집음", "status": "충족 근거 있음", "citations": [STORE], "reason": "x"}
                out.append({"duty": d, **flip})
            else:
                out.append({"duty": d, "result": "유지", "citations": [], "reason": "y"})
        return _reply({"results": out})

    return send


def _run(root: Path, batch: str, **kw) -> tuple[dict, list]:
    log: list = []
    inv = AgentJudge("claude-haiku-5-5", fake_investigator())
    chk = AgentJudge("claude-sonnet-5-5", fake_checker(log))
    limits = rv.Limits(usd=kw.pop("usd", 5.0), seconds=300, concurrency=2, batch=batch)
    return rv.review(root, inv, chk, limits, throttles=(rv.Throttle(2), rv.Throttle(2)), **kw), log


@pytest.mark.parametrize("batch", ["feature", "duty"])
def test_the_whole_path_runs_on_fake_answers_and_matches_the_schema(tmp_path, batch):
    doc, log = _run(_repo(tmp_path), batch, use_static=batch == "feature")
    errors = list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(doc))
    assert not errors, [f"{list(e.path)}: {e.message[:200]}" for e in errors[:5]]

    feats = {f["id"]: f for f in doc["profile"]["features"]}
    assert feats["genai"]["sources"] == ["model"] and feats["genai"]["model_citations"][0]["file"] == "server/answer.py"
    assert "location" not in feats  # 지어낸 인용으로는 기능을 더하지 못한다
    assert "removed" not in feats.get("auth", {})  # 인용 없이 빼지 못한다
    assert [n["id"] for n in doc["data_flow"]["nodes"]] == ["n1", "n2", "n3"]
    assert [(e["from"], e["to"]) for e in doc["data_flow"]["edges"]] == [("n1", "n2")]

    items = doc["checklist"]
    assert items and {i["status"] for i in items} <= {"evidence-found", "to-check", "not-applicable", "unknown"}
    by_first = {}
    for i in items:
        by_first.setdefault(i["first"]["answered"], []).append(i)
    # 시험 파일·지어낸 인용으로는 목록에서 빼지 못한다
    assert any(c["why"] == "test-file" for i in items for c in i["first"]["citations"])
    for i in items:
        if i["first"]["answered"] in ("evidence-found", "not-applicable") and not any(
            c["ok"] for c in i["first"]["citations"]
        ):
            assert i["first"]["status"] == "to-check"
    # '확인할 것'은 반박이 인용과 함께 뒤집으면 충족이 된다
    flipped = [i for i in items if i["verification"]["result"] == "overturned"]
    assert flipped and all(i["status"] == "evidence-found" for i in flipped)
    assert all("앞 판단" in p for p in log)
    run = doc["run"]
    assert run["calls"] > 0 and run["usd_estimate"] > 0 and run["citations_rejected"] > 0
    assert run["status_counts"] and sum(run["status_counts"].values()) == len(items)
    if batch == "feature":
        assert run["static"]["ran"]
        kid = next(i for i in items if i["duty"] == "pipa-22-2-1")
        assert kid["krcore"] and kid["static"] and kid["static"][0]["file"] == "src/routes/signup.ts"
    else:
        assert all(len(q.get("duties", [])) <= 1 for q in run["questions"] if q["stage"] == "investigate")


def test_the_cost_cap_leaves_duties_unknown_and_says_why(tmp_path):
    doc, _ = _run(_repo(tmp_path), "duty", use_static=False, usd=0.16)
    unknown = [i for i in doc["checklist"] if i["status"] == "unknown"]
    assert unknown and all(i["not_answered"] == "cost-cap" for i in unknown)
    assert doc["run"]["not_asked"]["cost-cap"] == len(unknown)
    assert doc["run"]["usd_estimate"] <= 0.16
    # 상한에 걸리면 '거의 모든 서비스'와 가입·로그인·AI·외부 전송부터 묻는다
    asked = [i["feature"] for i in doc["checklist"] if i["asked"]]
    assert asked and asked[0] == "common"
    jsonschema.validate(doc, SCHEMA)


def test_a_prose_answer_is_rewritten_once_into_json(tmp_path):
    """답이 JSON 이 아니면 도구 없이 한 번 더 JSON 으로 옮겨 달라고 묻는다(11/11 실측: 이해 단계가 글로 끝났다)."""
    inner = fake_investigator()

    def send(body):
        prompt = _text(body)
        if prompt.startswith("이 저장소가 어떤 서비스인지"):
            return _reply_text("두 파일을 더 읽겠습니다.")
        if prompt.startswith("아래는 네가 바로 앞에서 낸 답이다"):
            assert body["tool_choice"]["type"] == "none"
            return inner({"messages": [{"content": "이 저장소가 어떤 서비스인지"}], "tool_choice": {"type": "none"}})
        return inner(body)

    inv = AgentJudge("claude-haiku-5-5", send)
    chk = AgentJudge("claude-sonnet-5-5", fake_checker([]))
    doc = rv.review(_repo(tmp_path), inv, chk, rv.Limits(concurrency=1), use_static=False)
    q = doc["run"]["questions"][0]
    assert q["stage"] == "understand" and q["repaired"] and q["failure"] is None and q["calls"] == 2
    assert doc["profile"]["summary"] and doc["run"]["understanding"]["answered"]


def _reply_text(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "usage": {"input_tokens": 10, "output_tokens": 5}}


def test_the_throttle_halves_on_429():
    t = rv.Throttle(4)
    t.saw(500)
    assert t.limit == 4
    t.saw(429)
    t.saw(429)
    t.saw(429)
    assert (t.limit, t.rate_limited) == (1, 3)
