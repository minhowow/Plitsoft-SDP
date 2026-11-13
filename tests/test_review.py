"""policypack review: 이해 → 의무별 근거 찾기 → 반박을 가짜 답으로 끝까지 돌린다. 모델 호출 0회."""

from __future__ import annotations

import json
import re
import zlib
from pathlib import Path

import pytest

from policypack import review as rv
from policypack.judge.agent import AgentAnswer, AgentJudge
from policypack.review import prompts as P

jsonschema = pytest.importorskip("jsonschema")
SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "review-2.json").read_text(encoding="utf-8"))

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

SIGNUP = {"file": "src/routes/signup.ts", "line": 4, "text": "const { email, name, birthDate } = req.body;"}
STORE = {
    "file": "src/routes/signup.ts",
    "line": 9,
    "text": "await db.user.create({ data: { email, name, birthDate } })",
}
OPENAI = {"file": "server/answer.py", "line": 4, "text": "return client.chat.completions.create("}
FAKE = {"file": "src/routes/signup.ts", "line": 2, "text": "verifyGuardianConsent(birthDate)"}
TEST_LINE = {"file": "tests/signup.test.ts", "line": 2, "text": 'expect(signup({ birthDate: "2015-01-01" }))'}
ABSENT = {"pattern": "주민등록번호|residentNumber", "path": ".", "hits": 0}
PRESENT_BUT_CLAIMED_ZERO = {"pattern": "birthDate", "path": ".", "hits": 0}
NO_CONDITION = {"applies": "아니오", "condition": "주민등록번호를 받지 않는다", "basis": "처리 없음"}


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


def _reply_text(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "usage": {"input_tokens": 10, "output_tokens": 5}}


def _node(nid: str, kind: str, label: str, cite: dict) -> dict:
    return {"id": nid, "kind": kind, "label": label, "data": ["생년월일"], "citations": [cite]}


UNDERSTOOD = {
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

# 의무마다 정해진 가짜 답(의무 id 의 crc32 로 고른다). 받는 조건이 어떻게 걸리는지 하나씩 보인다
ANSWERS = [
    ("충족 근거 있음", [TEST_LINE], [], {"shows": "행위"}),  # 시험 파일 인용 → 저장소 밖에서 확인할 것
    # 다시 돌리면 줄 수가 다르다 → 걸리지 않는 것으로 보임(그 기능이 있으면 걸리는 의무면 코드에서 본 것)
    ("해당 없음", [], [PRESENT_BUT_CLAIMED_ZERO], NO_CONDITION),
    ("해당 없음", [], [ABSENT], NO_CONDITION),  # 증명됨 → 해당 없음
    ("확인할 것(코드에서 본 것)", [STORE], [ABSENT], {"applies": "예", "missing": "생년월일 확인이 없음"}),
    ("확인할 것(코드에서 본 것)", [FAKE], [], {}),  # 지어낸 인용 → 저장소 밖에서 확인할 것
    ("확인할 것(해당 여부)", [], [], {}),
]


def answer_for(duty: str) -> tuple[str, list, list, dict]:
    return ANSWERS[zlib.crc32(duty.encode()) % len(ANSWERS)]


def fake_investigator(answer=None):
    """이해 단계는 신호가 못 본 AI 기능과 개인정보 흐름을 낸다. 의무마다 answer(기본 answer_for)의 답.
    첫 답 앞에 도구를 한 번 쓴다."""
    seen: set[str] = set()
    answer = answer or answer_for

    def send(body: dict) -> dict:
        prompt = _text(body)
        if prompt.startswith("이 저장소가 어떤 서비스인지"):
            return _reply(UNDERSTOOD)
        ids = re.findall(r"^- \[([^\]]+)\]", prompt, re.M)
        key = ",".join(ids)
        if key not in seen and body["tool_choice"]["type"] != "none":
            seen.add(key)
            tool = {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "src/routes/signup.ts"}}
            return {"content": [tool], "usage": {"input_tokens": 500, "output_tokens": 20}}
        results = []
        for d in ids:
            status, cites, searches, extra = answer(d)
            results.append(
                {
                    "duty": d,
                    "status": status,
                    "citations": cites,
                    "searches": searches,
                    **extra,
                    "question": "어디서?",
                    "reason": d,
                }
            )
        return _reply({"results": results})

    return send


def fake_checker(log: list):
    """검색 증명이 없는 '해당 없음'은 코드에서 본 것으로, 코드에서 본 것은 충족으로, 저장소 밖은 해당 없음(검색
    증명)으로 뒤집는다. 저장소 밖을 뒤집을 때는 조문 밖 요건이었다고 적는다."""

    def send(body: dict) -> dict:
        prompt = _text(body)
        log.append(prompt)
        out = []
        for block in re.split(r"^(?=- \[)", prompt, flags=re.M)[1:]:
            d = re.match(r"- \[([^\]]+)\]", block).group(1)
            if "앞 판단: 해당 없음(검색 증명 없음)" in block:
                flip = {"result": "뒤집음", "status": "확인할 것(코드에서 본 것)", "citations": [STORE], "searches": []}
            elif "앞 판단: 확인할 것(코드에서 본 것)" in block:
                flip = {"result": "뒤집음", "status": "충족 근거 있음", "citations": [STORE], "shows": "행위"}
            elif "앞 판단: 확인할 것(저장소 밖)" in block:
                flip = {
                    "result": "뒤집음",
                    "status": "해당 없음",
                    "citations": [],
                    "searches": [ABSENT],
                    "off_quote": True,
                    **NO_CONDITION,
                }
            else:
                flip = {"result": "유지", "citations": [], "searches": []}
            out.append({"duty": d, "reason": "x", **flip})
        return _reply({"results": out})

    return send


def _run(root: Path, batch: str, **kw) -> tuple[dict, list]:
    log: list = []
    inv = AgentJudge("claude-haiku-5-5", kw.pop("investigator", None) or fake_investigator())
    chk = AgentJudge("claude-sonnet-5-5", kw.pop("checker", None) or fake_checker(log))
    limits = rv.Limits(usd=kw.pop("usd", 5.0), seconds=300, concurrency=2, batch=batch)
    return rv.review(root, inv, chk, limits, throttles=(rv.Throttle(2), rv.Throttle(2)), **kw), log


def _valid(doc: dict) -> None:
    errors = list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(doc))
    assert not errors, [f"{list(e.path)}: {e.message[:200]}" for e in errors[:5]]


@pytest.mark.parametrize("batch", ["duty", "feature"])
def test_the_whole_path_runs_on_fake_answers_and_matches_the_schema(tmp_path, batch):
    doc, log = _run(_repo(tmp_path), batch, use_static=batch == "duty")
    _valid(doc)

    feats = {f["id"]: f for f in doc["profile"]["features"]}
    assert feats["genai"]["sources"] == ["model"] and feats["genai"]["model_citations"][0]["file"] == "server/answer.py"
    assert "location" not in feats  # 지어낸 인용으로는 기능을 더하지 못한다
    assert "removed" not in feats.get("auth", {})  # 인용 없이 빼지 못한다
    assert doc["profile"]["platforms"] == ["server"]  # express 만 있다. 화면 파일이 있어도 웹이 아니다
    assert "web-ui" not in feats
    assert doc["run"]["lacks"] == "screen"  # 서버만이라 화면이 하는 의무의 '코드에서 본 것'은 저장소 밖이다
    screen = rv._sides()["screen"]
    banned = {d["id"] for d in rv.load_duties() if d["prohibition"]}

    def seen(duty: str) -> str:
        return "check-outside" if duty in screen else "seen-in-code"

    assert [n["id"] for n in doc["data_flow"]["nodes"]] == ["n1", "n2", "n3"]
    assert [(e["from"], e["to"]) for e in doc["data_flow"]["edges"]] == [("n1", "n2")]

    items = doc["checklist"]
    firsts = [i["first"] for i in items if i["first"]]
    firsts_of = [i for i in items if i["first"]]
    rows = {d["id"]: d for d in rv.load_duties()}

    def forced(i: dict) -> bool:
        """그 기능이 있으면 걸리는 의무로 고정되는가(AI 고지는 프로필의 생성형 신호가 있을 때만)."""
        return rv._always(rows[i["duty"]], feats.get(i["feature"]))

    # 받는 조건: 시험 파일·지어낸 인용은 코드에서 본 것·충족이 되지 못하고, 검색 줄 수가 다른 해당 없음은 '보임'으로
    # 남는다. 그 기능이 있으면 걸리는 의무(가입의 약관 고지, AI 고지)는 해당 없음이 되지 못한다
    for i in items:
        f = i["first"]
        if not f:
            continue
        ok = any(c["ok"] for c in f["citations"])
        proven = bool(f["searches"]) and all(s["ok"] for s in f["searches"])
        if f["answered"] == "evidence-found":
            assert f["status"] == ("evidence-found" if ok else "check-outside")
        if f["answered"] == "seen-in-code" and i["duty"] in banned:  # 금지 행위의 인용이 없다
            assert f["status"] == ("not-applicable" if proven else "likely-not-applicable")
            assert f["gate"]["why"] == "prohibition"
        elif f["answered"] == "seen-in-code":
            assert f["status"] == (seen(i["duty"]) if ok else "check-outside")
            assert (f["gate"] or {}).get("why") == ("other-side" if ok and i["duty"] in screen else None)
        if f["answered"] == "not-applicable":
            if forced(i):
                assert f["status"] == seen(i["duty"]) and f["gate"]["note"].startswith(feats[i["feature"]]["name"])
                assert f["gate"]["why"] == ("other-side" if i["duty"] in screen else "condition-present")
                assert any(c["ok"] for c in f["citations"]) and f["reason"].startswith(feats[i["feature"]]["name"])
            elif i["duty"] in rv._audience():  # 이용자가 누구인지에 걸리는 의무는 코드만으로 해당 없음이 아니다
                assert f["status"] == "check-applicability" and f["gate"]["why"] == "audience"
            else:
                assert f["status"] == ("not-applicable" if proven else "likely-not-applicable") and f["gate"] is None
    whys = {s["why"] for f in firsts for s in f["searches"]}
    assert {"match", "mismatch"} <= whys
    mismatch = next(s for f in firsts for s in f["searches"] if s["why"] == "mismatch")
    assert mismatch["claimed"] == 0 and mismatch["found"] > 0
    # 이 픽스처에서 '걸리지 않는 것으로 보임'이 될 의무는 아동 동의(audience)뿐이라 해당 여부부터다(반박 시험에서 본다)
    assert {f["status"] for f in firsts} >= {"check-outside", "check-applicability", "not-applicable", "seen-in-code"}

    # AI 기능은 이해 단계가 더한 것뿐이라(Python 서버의 호출, 프로필 신호 없음) 생성형 신호가 아니다.
    # AI 사전 고지·결과물 표시는 묻지 않고 해당 여부다
    # 그래도 생성형 AI 기능이 있으니 AI 고지는 묻는다. 그 기능이 있으면 걸리는 의무로 고정하지는 않는다
    held = {i["duty"] for i in items if i.get("not_answered") == "not-generative"}
    assert not held and not rv.generative(feats["genai"]) and set(rv._generative()) <= {i["duty"] for i in firsts_of}
    # 반박: 해당 여부는 묻지 않고, 뒤집기는 인용·검색 조건을 넘은 것만
    for i in items:
        if i["status"] == "check-applicability":
            why = "not-generative" if i["duty"] in held else "business-judgment"
            assert i["verification"] == {"result": "not-run", "why": why}
    flipped = [i for i in items if i["verification"]["result"] == "overturned"]
    assert flipped
    for i in flipped:
        before = i["first"]["status"]
        if before in rv.DROPS:
            assert i["status"] == seen(i["duty"])
        elif before == "seen-in-code":
            assert i["status"] == "evidence-found" and i["verification"]["shows"] == "행위"
        else:
            assert i["status"] == "not-applicable" and i["verification"]["off_quote"] and i["searches"][0]["ok"]
            assert not forced(i)
    # 반박이 해당 없음으로 뒤집으려 해도 같은 관문(그 기능이 있으면 걸리는 의무는 받지 않는다)
    for i in items:
        v = i["verification"]
        if v["result"] == "overturn-ungrounded" and v.get("status") == "not-applicable":
            assert forced(i) and v["gate"]["why"] == "condition-present"
    assert not any(f"앞 판단: {P.SAID['check-applicability']}" in p for p in log)  # 해당 여부는 반박하지 않는다

    # 순서: 갈래 순, rank 는 1부터, summary 의 맨 위 다섯 건
    order = [P.ORDER.index(i["status"]) for i in items]
    assert order == sorted(order) and [i["rank"] for i in items] == list(range(1, len(items) + 1))
    assert doc["summary"]["top"] == [i["duty"] for i in items[:5]]
    assert sum(doc["summary"]["counts"].values()) == len(items)
    assert all(i["status_label"] == P.STATUS_LABEL[i["status"]] for i in items)
    run = doc["run"]
    assert run["calls"] > 0 and run["usd_estimate"] > 0 and run["citations_rejected"] > 0
    assert run["searches"] > 0 and run["searches_rejected"] > 0
    if batch == "duty":
        assert run["static"]["ran"]
        kid = next(i for i in items if i["duty"] == "pipa-22-2-1")
        assert kid["krcore"] and kid["static"] and kid["static"][0]["file"] == "src/routes/signup.ts"
        assert all(len(q.get("duties", [])) <= 1 for q in run["questions"] if q["stage"] == "investigate")


def test_a_saved_understanding_is_reused_without_asking(tmp_path):
    root = _repo(tmp_path)
    first, _ = _run(root, "duty", use_static=False)

    def no_understanding(body):
        assert not _text(body).startswith("이 저장소가 어떤 서비스인지"), "이해 단계를 다시 물었다"
        return inner(body)

    inner = fake_investigator()
    again, _ = _run(root, "duty", use_static=False, reuse=first, investigator=no_understanding)
    _valid(again)
    assert not any(q["stage"] == "understand" for q in again["run"]["questions"])
    assert again["run"]["understanding"]["reused"]
    assert [f["id"] for f in again["profile"]["features"]] == [f["id"] for f in first["profile"]["features"]]

    def flow(d):
        cut = [(c["file"], c["line"], c["ok"]) for x in d["nodes"] + d["edges"] for c in x["citations"]]
        return [x.get("id") or (x["from"], x["to"]) for x in d["nodes"] + d["edges"]], cut

    assert flow(again["data_flow"]) == flow(first["data_flow"])
    assert again["profile"]["summary"] == first["profile"]["summary"]


def test_the_cost_cap_leaves_duties_unknown_and_says_why(tmp_path):
    cap = rv.RESERVE["claude-haiku-5-5"] + 0.001
    doc, _ = _run(_repo(tmp_path), "duty", use_static=False, usd=cap)
    unknown = [i for i in doc["checklist"] if i["status"] == "unknown"]
    assert unknown and all(i["not_answered"] == "cost-cap" for i in unknown)
    assert doc["run"]["not_asked"]["cost-cap"] == len(unknown)
    assert doc["run"]["usd_estimate"] <= cap
    # 상한에 걸리면 '거의 모든 서비스'와 가입·AI·외부 전송부터 묻는다
    asked = [q["feature"] for q in doc["run"]["questions"] if q["stage"] == "investigate" and q.get("calls")]
    assert asked and asked[0] == "common"
    _valid(doc)


def test_cost_is_the_official_price_for_each_call():
    # sonnet 5.5: 입력 $2, 5분 캐시 쓰기 $2.5, 캐시 읽기 $0.1, 출력 $10 (100만 토큰당)
    m = 1_000_000
    assert rv.usd("claude-sonnet-5-5", {"input_tokens": m, "output_tokens": m}) == pytest.approx(12.0)
    cached = {"cache_creation_input_tokens": m, "cache_read_input_tokens": m}
    assert rv.usd("claude-sonnet-5-5", cached) == pytest.approx(2.6)
    # haiku 5.5: 호출 하나의 프롬프트(입력 + 캐시 쓰기·읽기)가 10만 토큰을 넘으면 그 호출의 모든 단가가 5배
    short = {"input_tokens": 50_000, "cache_read_input_tokens": 40_000, "output_tokens": 1000}
    long = {**short, "cache_read_input_tokens": 60_000}
    assert rv.usd("claude-haiku-5-5", short) == pytest.approx(0.0059)
    assert rv.usd("claude-haiku-5-5", long) == pytest.approx(0.0305)
    # 호출마다 매긴다: 9만 토큰 호출 둘은 18만 토큰 호출 하나가 아니다
    ans = AgentAnswer(per_call=[short, short])
    assert rv.cost("claude-haiku-5-5", ans) == pytest.approx(0.0118)
    # 표에 없는 모델은 가장 비싼 단가로 세고, 상한 앞에 크게 남긴다
    assert rv.usd("claude-sonnet-4-5", {"input_tokens": m}) == pytest.approx(15.0)
    spend = rv.Spend(1.0)
    assert spend.allows("claude-sonnet-5-5") and not spend.allows("claude-sonnet-4-5")


def test_a_prose_answer_is_rewritten_once_into_json(tmp_path):
    """답이 JSON 이 아니면 도구 없이 한 번 더 JSON 으로 옮겨 달라고 묻는다(11/11 실측: 이해 단계가 글로 끝났다)."""
    inner = fake_investigator()

    def send(body):
        prompt = _text(body)
        if prompt.startswith("이 저장소가 어떤 서비스인지"):
            return _reply_text("두 파일을 더 읽겠습니다.")
        if prompt.startswith("아래는 네가 바로 앞에서 낸 답이다"):
            assert body["tool_choice"]["type"] == "none"
            return _reply(UNDERSTOOD)
        return inner(body)

    doc, _ = _run(_repo(tmp_path), "duty", use_static=False, investigator=send)
    q = doc["run"]["questions"][0]
    assert q["stage"] == "understand" and q["repaired"] and q["failure"] is None and q["calls"] == 2
    assert doc["profile"]["summary"] and doc["run"]["understanding"]["answered"]


def test_absence_is_proven_by_rerunning_the_search(tmp_path):
    root = _repo(tmp_path)
    got, proven = rv.prove(root, [{"pattern": "birthDate", "hits": 3}, {"pattern": "주민등록번호", "hits": 0}])
    assert proven and [s["found"] for s in got] == [3, 0]  # 가입 파일 두 줄 + 시험 파일 한 줄
    for bad, why in (
        ({"pattern": "birthDate", "hits": 0}, "mismatch"),
        ({"pattern": "(", "hits": 0}, "bad-pattern"),
        ({"pattern": "x", "hits": 0}, "bad-pattern"),
        ({"pattern": "birthDate", "path": "../..", "hits": 0}, "outside-repo"),
        ({"pattern": "birthDate"}, "no-count"),
    ):
        got, proven = rv.prove(root, [bad])
        assert not proven and got[0]["why"] == why
    assert rv.prove(root, []) == ([], False)


def test_the_throttle_halves_on_429():
    t = rv.Throttle(4)
    t.saw(500)
    assert t.limit == 4
    t.saw(429)
    t.saw(429)
    t.saw(429)
    assert (t.limit, t.rate_limited) == (1, 3)


def _duty(did: str) -> dict:
    return next(d for d in rv.load_duties() if d["id"] == did)


def test_not_applicable_needs_the_condition_itself_to_be_absent():
    """'해당 없음'은 걸리는 조건 자체가 없을 때만이다. 지킨 처리가 없다는 것은 '코드에서 본 것'이다(11/12 실측: 약관이
    아예 없는 가입, 탈퇴 경로가 없는 쇼핑몰, 철회 기능이 없는 위치 서비스를 해당 없음으로 읽었다)."""
    signup = {"id": "signup", "name": "회원 가입·개인정보 수집", "evidence": [], "model_citations": []}
    terms, sensitive = _duty("tcra-3-2"), _duty("pipa-23-1")
    no = rv.said(
        {
            "applies": "아니오",
            "condition": "약관을 쓰지 않는다",
            "missing": "약관 고지 화면이 없음",
            "basis": "처리 없음",
        }
    )

    # 그 기능이 있으면 걸리는 의무: 기능이 있으면 증명된 검색이 있어도 해당 없음이 아니다
    status, gate = rv.absent(terms, no, True, signup, False)
    assert status == "seen-in-code" and gate["why"] == "condition-present" and "약관 고지 화면이 없음" in gate["note"]
    # 기능을 이해 단계가 뺐으면 조건을 따른다
    assert rv.absent(terms, no, True, {**signup, "removed": {}}, False) == ("not-applicable", None)
    # 조건은 있다고 답했으면 코드에서 본 것(인용이 없으면 해당 여부부터)
    yes = rv.said({"applies": "예", "condition": "민감정보 입력란이 있다"})
    assert rv.absent(sensitive, yes, True, None, True)[0] == "seen-in-code"
    assert rv.absent(sensitive, yes, True, None, False)[0] == "check-applicability"
    # 걸리는 조건이 없다는 말이 없으면 해당 여부부터
    for s in (
        {},
        {"applies": "모름", "condition": "x"},
        {"applies": "아니오"},
        {"applies": "아니오", "condition": "x"},
    ):
        status, gate = rv.absent(sensitive, rv.said(s), True, None, False)
        assert status == "check-applicability" and gate["why"] == "no-condition"
    # 조건이 없고 검색이 증명되면 해당 없음, 아니면 걸리지 않는 것으로 보임
    assert rv.absent(sensitive, no, True, None, False) == ("not-applicable", None)
    assert rv.absent(sensitive, no, False, None, False) == ("likely-not-applicable", None)


def test_a_missing_check_does_not_prove_the_condition_is_absent():
    """나이·본인·지역을 확인하는 장치가 없다는 것은 그런 이용자가 없다는 증명이 아니다(11/12 재실행: 나이 확인이 없는
    가입을 '아동 동의 해당 없음'으로 읽었다). 이용자가 누구인지에 걸리는 의무(audience)는 답과 상관없이, 다른 의무는
    답이 그것을 근거로 들 때 '해당 여부부터'다."""
    signup = {"id": "signup", "name": "회원 가입·개인정보 수집", "evidence": [], "model_citations": []}
    kid, sensitive = _duty("pipa-22-2-1"), _duty("pipa-23-1")
    assert rv._audience()["pipa-22-2-1"] == "signup"
    no_age_check = {"applies": "아니오", "condition": "나이를 받아 14세 미만을 가르는 가입 흐름이 없음"}
    for basis in ("처리 없음", "확인 장치 없음"):
        for feature in (signup, None):
            status, gate = rv.absent(kid, rv.said({**no_age_check, "basis": basis}), True, feature, False)
            assert status == "check-applicability" and gate["why"] == "audience" and "증명이 아니" in gate["note"]
    status, gate = rv.absent(sensitive, rv.said({**no_age_check, "basis": "확인 장치 없음"}), True, None, False)
    assert status == "check-applicability" and gate["why"] == "missing-check"
    no = rv.said({"applies": "아니오", "condition": "민감정보 입력란이 없다", "basis": "처리 없음"})
    assert rv.absent(sensitive, no, True, None, False) == ("not-applicable", None)
    assert all("확인 장치 없음" in t for t in (P.CONDITION, P.INVESTIGATE, P.REBUT))


def test_an_unknown_applicability_goes_to_check_applicability(tmp_path):
    """걸리는지 모른다고 답한 '확인할 것'은 '해당 여부부터 확인할 것'이다(11/12 재실행: 외부 AI 호출을 '제3자 제공'으로
    보고 "제공인지 위탁인지는 개발자 판단"이라면서 '코드에서 본 것'에 뒀다). 그 기능이 있으면 걸리는 의무는 그대로다."""
    ok = [{"file": "a.ts", "line": 1, "text": "x", "ok": True, "why": "grounded"}]
    signup = {"id": "signup", "name": "회원 가입·개인정보 수집", "evidence": [], "model_citations": []}
    third, terms = _duty("pipa-17-2"), _duty("tcra-3-2")
    unsure = rv.said({"applies": "모름", "condition": "대화를 외부 AI 로 보낸다"})
    for answered in ("seen-in-code", "check-outside"):
        status, gate = rv.accept(third, unsure, answered, ok, False, None)
        assert status == "check-applicability" and gate == {**gate, "from": answered, "why": "applies-unknown"}
    assert rv.accept(terms, unsure, "seen-in-code", ok, False, signup) == ("seen-in-code", None)
    assert rv.accept(third, rv.said({"applies": "예"}), "seen-in-code", ok, False, None) == ("seen-in-code", None)

    # 전체 경로: 조사 답이 모두 '모름'이면 기능이 있으면 걸리는 의무 말고는 해당 여부부터, 반박하지 않는다
    def unsure_answer(_duty_id):
        return ("확인할 것(코드에서 본 것)", [STORE], [], {"applies": "모름", "condition": "가입을 받는다"})

    doc, log = _run(_repo(tmp_path), "duty", use_static=False, investigator=fake_investigator(unsure_answer))
    _valid(doc)
    feats = {f["id"]: f for f in doc["profile"]["features"]}
    rows, screen = {d["id"]: d for d in rv.load_duties()}, rv._sides()["screen"]  # 픽스처는 서버만이다
    for i in doc["checklist"]:
        if not i["asked"]:
            continue
        if rv._always(rows[i["duty"]], feats.get(i["feature"])):
            assert i["first"]["status"] == ("check-outside" if i["duty"] in screen else "seen-in-code"), i["duty"]
        else:
            assert i["status"] == "check-applicability" and i["first"]["gate"]["why"] == "applies-unknown", i["duty"]
            assert i["verification"] == {"result": "not-run", "why": "business-judgment"}

    # 반박이 빼는 답을 깨면 '코드에서 본 것', 그러면서 걸리는지 모른다고 하면 해당 여부부터
    def drop(_duty_id):
        return ("해당 없음", [], [PRESENT_BUT_CLAIMED_ZERO], NO_CONDITION)

    def split_checker(body):
        out = []
        for d in re.findall(r"^- \[([^\]]+)\]", _text(body), re.M):
            unsure = zlib.crc32(d.encode()) % 2 == 0
            status = "확인할 것(해당 여부)" if unsure else "확인할 것(코드에서 본 것)"
            applies = "모름" if unsure else "예"
            out.append({"duty": d, "result": "뒤집음", "status": status, "applies": applies, "citations": [STORE]})
        return _reply({"results": out})

    doc, _ = _run(
        _repo(tmp_path), "duty", use_static=False, investigator=fake_investigator(drop), checker=split_checker
    )
    _valid(doc)
    flipped = [i for i in doc["checklist"] if i["verification"]["result"] == "overturned"]
    assert flipped and all(i["first"]["status"] == "likely-not-applicable" for i in flipped)
    unsure = [i for i in flipped if i["verification"]["applies"] == "모름"]
    sure = [i for i in flipped if i["verification"]["applies"] == "예"]
    assert unsure and sure
    assert all(i["status"] == "check-applicability" for i in unsure)
    assert all(i["verification"]["gate"]["why"] == "applies-unknown" for i in unsure)
    for i in sure:  # 서버만인 저장소라 화면이 하는 의무는 저장소 밖이다
        side = i["duty"] in screen
        assert i["status"] == ("check-outside" if side else "seen-in-code"), i["duty"]
        assert (i["verification"]["gate"] or {}).get("why") == ("other-side" if side else None)
    assert all(i["first"]["basis"] == "처리 없음" for i in flipped)  # 조사 답의 근거도 출력에 남는다
    kid = next(i for i in doc["checklist"] if i["duty"] == "pipa-22-2-1")  # 조사 답부터 해당 여부(audience)
    assert kid["status"] == "check-applicability" and kid["first"]["gate"]["why"] == "audience"


def test_evidence_must_show_the_act_not_a_name_or_a_default():
    """'충족 근거 있음'은 인용이 조문이 요구하는 행위 자체일 때만이다(11/12 실측: helmet 기본값으로 전송 암호화 충족,
    메뉴의 'GenAI' 글자로 AI 사전 고지 충족)."""
    ok = [{"file": "a.ts", "line": 1, "text": "x", "ok": True, "why": "grounded"}]
    d = _duty("aiact-31-1")
    assert rv.accept(d, rv.said({"shows": "행위"}), "evidence-found", ok, False, None) == ("evidence-found", None)
    for shows in ("이름·기본값", None):
        status, gate = rv.accept(d, rv.said({"shows": shows}), "evidence-found", ok, False, None)
        assert status == "seen-in-code" and gate["why"] == "name-or-default"
    assert rv.accept(d, rv.said({"shows": "행위"}), "evidence-found", [], False, None) == ("check-outside", None)


def test_the_rebuttal_passes_the_same_gate(tmp_path):
    """반박이 '확인할 것'을 해당 없음·충족으로 뒤집을 때도 같은 관문이다.
    프롬프트에는 조건과 행위를 따지라는 말이 있다."""

    def outside(_duty_id):
        return ("확인할 것(저장소 밖)", [], [], {})

    doc, log = _run(_repo(tmp_path), "duty", use_static=False, investigator=fake_investigator(outside))
    _valid(doc)
    items = {i["duty"]: i for i in doc["checklist"]}
    terms = items["tcra-3-2"]  # 가입 기능이 있다 → 해당 없음으로 뒤집지 못한다
    assert terms["status"] == "check-outside" and terms["verification"]["result"] == "overturn-ungrounded"
    assert terms["verification"]["gate"]["why"] == "condition-present"
    flipped = [i for i in items.values() if i["verification"]["result"] == "overturned"]
    assert flipped and all(i["status"] == "not-applicable" for i in flipped)
    assert all(i["duty"] != "tcra-3-2" for i in flipped)
    kid = items["pipa-22-2-1"]  # 이용자가 누구인지에 걸리는 의무 → 해당 없음으로 뒤집지 못한다
    assert kid["status"] == "check-outside" and kid["verification"]["gate"]["why"] == "audience"
    assert all("이름·기본값" in p and "걸리는 조건인지 지킨 처리인지" in p for p in log)


def test_goods_duties_wait_for_a_goods_signal(tmp_path):
    """특정 품목(주류·도서 등)의 의무는 그 품목 신호가 없으면 묻지 않고 '해당 여부부터'의 맨 뒤에 한 묶음으로 싣는다.
    기능 안에서는 핵심 의무(일반 범위 → 흔한 것)를 먼저 묻는다."""
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"express": "4"}}))
    (tmp_path / "src" / "cart").mkdir(parents=True)
    (tmp_path / "src" / "cart" / "order.ts").write_text("export const order = (id) => db.order.create({ id });\n")
    doc, _ = _run(tmp_path, "duty", use_static=False, investigator=fake_investigator(lambda d: ANSWERS[5]))
    _valid(doc)
    goods = {d for g in rv.load_features()["goods"] for d in g["duties"]}
    asked = [d for q in doc["run"]["questions"] if q["stage"] == "investigate" for d in q["duties"]]
    assert asked and not goods & set(asked)
    held = [i for i in doc["checklist"] if i.get("group") == "goods"]
    assert {i["duty"] for i in held} == goods
    assert all(i["status"] == "check-applicability" and not i["asked"] for i in held)
    assert all(i["not_answered"] == "goods-not-detected" and i["verification"]["result"] == "not-run" for i in held)
    assert doc["summary"]["groups"] == [
        {"id": "goods", "label": rv.GOODS_LABEL, "status": "check-applicability", "duties": [i["duty"] for i in held]}
    ]
    applicability = [i for i in doc["checklist"] if i["status"] == "check-applicability"]
    assert applicability[-len(held) :] == held  # 갈래의 맨 뒤
    # 묻는 순서(동시에 물어 질문 기록의 순서는 조금 섞인다): 상거래 안에서는 일반 범위(표시광고법), 기능이 있으면
    # 걸리는 의무(탈퇴·해지를 가입처럼 등), 그다음은 흔한 것부터
    _, _, order, _ = rv.select(rv.profile(tmp_path), {"summary": "", "added": [], "removed": []}, {})
    commerce = [d for d in order if d["feature"] == "commerce"]
    whenever = set(rv._whenever())
    assert [d["scope"] for d in commerce[:2]] == ["general", "general"]
    core = [d for d in commerce[2:] if d["id"] in whenever]
    assert commerce[2 : 2 + len(core)] == core and {"ecom-5-4", "ecom-21-2-1-h4"} <= {d["id"] for d in core}
    rest = [d["freq"] for d in commerce[2 + len(core) :]]
    assert rest == sorted(rest, reverse=True)

    # 품목 신호(화면 문구의 '와인')가 생기면 그 품목 의무를 묻는다. 기능 안에서 맨 뒤다
    (tmp_path / "src" / "cart" / "menu.ts").write_text('export const MENU = ["와인", "치즈"];\n')
    doc, _ = _run(tmp_path, "duty", use_static=False, investigator=fake_investigator(lambda d: ANSWERS[5]))
    asked = [d for q in doc["run"]["questions"] if q["stage"] == "investigate" for d in q["duties"]]
    assert {"liquor-mail-6-0-0-2", "youth-28-4"} <= set(asked)
    _, _, order, skipped = rv.select(rv.profile(tmp_path), {"summary": "", "added": [], "removed": []}, {})
    commerce = [d["id"] for d in order if d["feature"] == "commerce"]
    assert set(commerce[-2:]) == {"liquor-mail-6-0-0-2", "youth-28-4"} and not goods & set(commerce[:-2])
    assert {"liquor-mail-6-0-0-2", "youth-28-4"}.isdisjoint(d["id"] for d in skipped)
    assert {g["id"] for g in doc["profile"]["goods"]} == {"liquor", "youth-harmful"}


def test_a_cut_search_says_the_total_and_the_gate_matches_it(tmp_path):
    """검색 결과가 잘려도 맞는 줄의 전체 수를 알려 주고, 관문은 그 수와 맞춰 본다(11/12 실측: 잘린 결과를 본 모델이
    줄 수를 60 으로 적어 검색 거절 213건 중 83건이 이것이었다)."""
    from policypack.judge.agent import SEARCH_HITS, RepoTools

    (tmp_path / "a.ts").write_text("".join(f"const password{i} = 1;\n" for i in range(50)))
    (tmp_path / "b.ts").write_text("".join(f"const password{i} = 1;\n" for i in range(30)))
    (tmp_path / "c.ts").write_text("const nothing = 1;\n")
    tools = RepoTools(tmp_path)
    out = tools.search("password")
    assert out.count("\n") == SEARCH_HITS and out.endswith(f"({SEARCH_HITS}개에서 자름. 맞는 줄은 모두 80개)")
    assert tools.matched == ["a.ts", "b.ts"]
    assert rv.prove(tmp_path, [{"pattern": "password", "hits": 80}])[1]
    assert not rv.prove(tmp_path, [{"pattern": "password", "hits": SEARCH_HITS}])[1]
    assert "맞는 줄은 모두" not in tools.search("nothing")


def test_a_guess_about_free_input_is_not_a_condition(tmp_path):
    """이용자가 자유 입력·사진에 그 정보를 넣을 수 있다는 추측은 걸리는 조건이 아니다(11/13 실측: 채팅 입력에
    민감정보가, 인증 사진에 신분증이 들어올 수 있다며 반박이 '해당 없음'을 '해당 여부부터'로 뒤집었다). 조사 답이면
    '걸리지 않는 것으로 보임', 반박의 뒤집기면 받지 않는다. 그 기능이 있으면 걸리는 의무와 이용자 의무는 그대로다."""
    ok = [{"file": "a.ts", "line": 1, "text": "x", "ok": True, "why": "grounded"}]
    signup = {"id": "signup", "name": "회원 가입·개인정보 수집", "evidence": [], "model_citations": []}
    guess = rv.said({"applies": "예", "condition": "채팅에 건강 정보를 쓸 수 있다", "trigger": "자유 입력 추측"})
    status, gate = rv.accept(_duty("pipa-23-1"), guess, "seen-in-code", ok, False, None)
    assert status == "likely-not-applicable" and gate["why"] == "free-input" and gate["from"] == "seen-in-code"
    # '코드에서 본 것' 후보를 내릴 때만 쓴다. 해당 여부(사업자인지 모름 등)·저장소 밖은 그대로다(11/13 3배치 실측)
    unsure = rv.said({"applies": "모름", "condition": "지능정보사업자인지 모른다", "trigger": "자유 입력 추측"})
    assert rv.accept(_duty("pipa-23-1"), guess, "check-applicability", ok, False, None) == ("check-applicability", None)
    assert rv.accept(_duty("pipa-23-1"), guess, "check-outside", ok, False, None) == ("check-outside", None)
    assert rv.accept(_duty("dincl-19-2"), unsure, "seen-in-code", ok, False, None)[0] == "check-applicability"
    assert rv.accept(_duty("tcra-3-2"), guess, "seen-in-code", ok, False, signup)[0] == "seen-in-code"
    assert rv.accept(_duty("pipa-22-2-1"), guess, "check-applicability", ok, False, signup)[0] == "check-applicability"
    field = rv.said({"applies": "예", "condition": "건강 상태 선택지가 있다", "trigger": "입력란·처리·저장"})
    assert rv.accept(_duty("pipa-23-1"), field, "seen-in-code", ok, False, None) == ("seen-in-code", None)
    assert all("자유 입력 추측" in t for t in (P.CONDITION, P.INVESTIGATE, P.REBUT))

    # 반박: 증명 없는 해당 없음을 '자유 입력 추측'으로 깨면 받지 않고, 입력란·처리·저장으로 깨면 받는다
    def drop(_duty_id):
        return ("해당 없음", [], [PRESENT_BUT_CLAIMED_ZERO], NO_CONDITION)

    def guessing_checker(body):
        out = []
        for d in re.findall(r"^- \[([^\]]+)\]", _text(body), re.M):
            trigger = "자유 입력 추측" if zlib.crc32(d.encode()) % 2 == 0 else "입력란·처리·저장"
            out.append(
                {"duty": d, "result": "뒤집음", "status": "확인할 것(코드에서 본 것)", "applies": "예",
                 "trigger": trigger, "citations": [STORE]}
            )  # fmt: skip
        return _reply({"results": out})

    doc, _ = _run(
        _repo(tmp_path), "duty", use_static=False, investigator=fake_investigator(drop), checker=guessing_checker
    )
    _valid(doc)
    held = [i for i in doc["checklist"] if (i["verification"].get("gate") or {}).get("why") == "free-input"]
    taken = [i for i in doc["checklist"] if i["verification"]["result"] == "overturned"]
    assert held and taken
    for i in held:
        assert i["verification"]["result"] == "overturn-ungrounded" and i["verification"]["trigger"] == "자유 입력 추측"
        assert i["status"] == "likely-not-applicable" and "받지 않았습니다" in i["verification"]["gate"]["note"]
    assert all(i["verification"]["trigger"] == "입력란·처리·저장" for i in taken)


def test_ai_notices_wait_for_a_generative_signal(tmp_path):
    """AI 사전 고지·결과물 표시는 생성형 AI 신호(꾸러미·import·호출·주소, 정적 검사, 그 글자가 있는 인용)가 있을 때만
    묻는다. 분류·인식 모델만 있거나 경로 낱말·이해 단계의 말뿐이면 묻지 않고 '해당 여부부터'다(11/13 실측: 포즈 분류
    모델을 'AI 기능'으로 보고 생성형 AI 결과물 표시를 '코드에서 본 것'으로 고정했다)."""
    cite = {"ok": True, "why": "grounded", "file": "Game.js", "line": 1}
    predict = "const prediction = await this.state.model.predict(posenetOutput);"
    pose = {"id": "genai", "name": "생성형 AI", "sources": ["model"], "evidence": [],
            "model_citations": [{**cite, "text": predict}]}  # fmt: skip
    assert not rv.generative(pose) and not rv.generative(None)
    # 프로필 신호(SDK 꾸러미·import·호출·주소)로만 정한다. 이해 단계의 인용, 정적 검사만으로는 아니다(11/13 3배치 실측:
    # 정적 검사가 피드 화면의 JSX 한 줄을 AI 호출로 잡았다)
    assert not rv.generative({**pose, "model_citations": [{**cite, "text": "return client.chat.completions.create("}]})
    assert not rv.generative({**pose, "sources": ["static"]})
    assert not rv.generative({**pose, "sources": ["signal"], "evidence": [{"signal": "path", "value": "ai"}]})
    for kind in ("package", "import", "call", "url"):
        assert rv.generative({**pose, "sources": ["signal"], "evidence": [{"signal": kind, "value": "openai"}]})
    # 프로필 신호는 '그 기능이 있으면 걸리는 의무'로 고정할 때만 요구한다. 신호 없이 AI 기능만 있으면 묻고 조사 답을
    # 따른다(11/13 4배치: Python 서버·자체 API·로컬 모델로 LLM 을 부르는 곳의 AI 고지가 묻지 않은 해당 여부로 갔다)
    notice, gen = _duty("aiact-31-2"), {**pose, "sources": ["signal"], "evidence": [{"signal": "url", "value": "x"}]}
    nothing = rv.said({"applies": "아니오", "condition": "생성 결과를 보여 주지 않는다", "basis": "처리 없음"})
    assert rv.accept(notice, nothing, "not-applicable", [], True, pose) == ("not-applicable", None)
    assert rv.accept(notice, nothing, "not-applicable", [], True, gen)[1]["why"] == "condition-present"
    llm = [{"file": "server/answer.py", "line": 4, "text": "return client.chat.completions.create(", "ok": True,
            "why": "grounded"}]  # fmt: skip
    seen_llm = rv.said({"applies": "예", "condition": "Python 서버가 LLM 을 부른다"})
    assert rv.accept(notice, seen_llm, "seen-in-code", llm, False, pose) == ("seen-in-code", None)

    gen = set(rv._generative())
    assert gen == {"aiact-31-1", "aiact-31-2"}
    pkg = {"dependencies": {"react": "18", "@teachablemachine/pose": "0.8"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Game.jsx").write_text(
        "export async function load(url) {\n  const model = await tmPose.load(url);\n  return model;\n}\n"
    )
    doc, _ = _run(tmp_path, "duty", use_static=False, investigator=fake_investigator(lambda d: ANSWERS[3]))
    _valid(doc)
    assert "ai-model" in {f["id"] for f in doc["profile"]["features"]}
    asked = {d for q in doc["run"]["questions"] if q["stage"] == "investigate" for d in q["duties"]}
    held = {i["duty"]: i for i in doc["checklist"] if i.get("not_answered") == "not-generative"}
    assert set(held) == gen and not gen & asked
    assert all(i["status"] == "check-applicability" and not i["asked"] and i["question"] for i in held.values())
    assert gen <= {d["id"] for d in doc["obligations"]["listed"] if d["in_checklist"]}

    # 생성형 꾸러미가 있으면 묻는다
    pkg = {"dependencies": {"react": "18", "openai": "4"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg))
    (tmp_path / "src" / "chat.ts").write_text('import OpenAI from "openai";\nexport const ai = new OpenAI();\n')
    doc, _ = _run(tmp_path, "duty", use_static=False, investigator=fake_investigator(lambda d: ANSWERS[3]))
    asked = {d for q in doc["run"]["questions"] if q["stage"] == "investigate" for d in q["duties"]}
    assert gen <= asked and not any(i.get("not_answered") == "not-generative" for i in doc["checklist"])


def test_a_whenever_duty_answered_as_applicability_goes_up_when_the_feature_is_confirmed():
    """그 기능이 있으면 걸리는 의무를 '해당 여부'로 답해도, 조사 답이 그 기능의 처리가 저장소에 있다고 보고 인용했으면
    '코드에서 본 것'이다(11/13 실측: 위치 기능이 있는데 확인자료 기록 의무를 '해당 여부'로 답해 그대로 남았다)."""
    line = {"file": "src/geo.ts", "line": 3, "signal": "call", "value": "navigator.geolocation", "what": "x"}
    location = {"id": "location", "name": "위치정보", "evidence": [line], "model_citations": []}
    ok = [{"file": "src/geo.ts", "line": 3, "text": "navigator.geolocation.getCurrentPosition(", "ok": True,
           "why": "grounded"}]  # fmt: skip
    record = _duty("locinfo-16-2")
    seen = rv.said({"applies": "예", "condition": "위치를 모아 서버로 보낸다"})
    status, gate = rv.accept(record, seen, "check-applicability", ok, False, location)
    assert status == "seen-in-code" and gate["from"] == "check-applicability" and gate["why"] == "condition-present"
    # 조사 답이 그 처리가 저장소에 있다고 보고(applies 예) 인용했을 때만 올린다. "처리가 저장소에 없다"(applies 모름,
    # 11/13 3배치 실측: 외부 판매 링크만 있는 책 SNS), 인용 없음, 기능을 뺀 경우, 그 밖의 의무는 그대로다
    unsure = rv.said({"applies": "모름", "condition": "주문·결제 처리가 저장소에 없다"})
    assert rv.accept(record, unsure, "check-applicability", ok, False, location) == ("check-applicability", None)
    assert rv.accept(record, seen, "check-applicability", [], False, location) == ("check-applicability", None)
    gone = {**location, "removed": {}}
    assert rv.accept(record, seen, "check-applicability", ok, False, gone) == ("check-applicability", None)
    assert rv.accept(_duty("locinfo-19-4"), seen, "check-applicability", ok, False, location)[0] == (
        "check-applicability"
    )
    # 서버만인 저장소면 화면이 하는 의무는 저장소 밖이다(위치 이용약관 공개)
    terms = _duty("locinfo-12-1")
    status, gate = rv.accept(terms, seen, "check-applicability", ok, False, location, "screen")
    assert status == "check-outside" and gate["why"] == "other-side" and gate["from"] == "check-applicability"


def test_a_one_sided_repository_checks_the_other_side_outside(tmp_path):
    """저장소가 서버만 또는 화면만이면 반대쪽이 하는 의무(화면 고지·동의 ↔ 서버 저장·암호화·제한)의 '코드에서 본 것'은
    '저장소 밖에서 확인할 것'이다(11/13 실측: 앱 서버 저장소에서 약관 고지·동의 고지를 '코드에서 본 것'으로 뒀다).
    화면만인지는 플랫폼과, JS·TS 밖의 서버 파일이 없는지로 가른다."""
    assert rv.lacks(tmp_path, ["server"]) == "screen"
    assert rv.lacks(tmp_path, ["web", "server"]) is None and rv.lacks(tmp_path, []) is None
    assert rv.lacks(tmp_path, ["mobile"]) == "server"
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "app.py").write_text("print(1)\n")
    assert rv.lacks(tmp_path, ["web"]) is None  # Python 서버가 있다
    sides = rv._sides()
    assert not sides["screen"] & sides["server"]
    ok = [{"file": "a.ts", "line": 1, "text": "x", "ok": True, "why": "grounded"}]
    yes = rv.said({"applies": "예", "condition": "가입을 받는다", "missing": "약관 고지가 없음"})
    terms, password = _duty("tcra-3-2"), _duty("safety-std-7-1")
    status, gate = rv.accept(terms, yes, "seen-in-code", ok, False, None, "screen")
    assert status == "check-outside" and gate == {**gate, "from": "seen-in-code", "why": "other-side"}
    assert rv.accept(terms, yes, "seen-in-code", ok, False, None, "server") == ("seen-in-code", None)
    assert rv.accept(password, yes, "seen-in-code", ok, False, None, "server")[0] == "check-outside"
    assert rv.accept(password, yes, "evidence-found", ok, False, None, "server")[0] == "check-outside"  # 이름·기본값
    act = rv.said({"applies": "예", "shows": "행위"})
    assert rv.accept(password, act, "evidence-found", ok, False, None, "server") == ("evidence-found", None)
    # 이 저장소의 줄을 인용해 빈틈 자체를 보였으면(shows 빈틈, 관문 통과) 옮기지 않는다(11/13 4배치: 관리자 화면 보호가
    # 상수 "true" 로 고정된 화면만 저장소)
    gap = rv.said({"applies": "예", "condition": "관리자 화면", "shows": "빈틈"})
    guard = _duty("safety-std-5-1")
    assert rv.accept(guard, gap, "seen-in-code", ok, False, None, "server") == ("seen-in-code", None)
    assert rv.accept(guard, yes, "seen-in-code", ok, False, None, "server")[0] == "check-outside"
    assert "빈틈" in P.SHOWS and "빈틈" in P.INVESTIGATE


def test_a_config_line_with_an_address_is_a_citation(tmp_path):
    """설정 파일의 줄은 인용으로 받지 않지만, 주소나 호스트 값이 글자 그대로 있는 줄(Sentry DSN, API 주소)은 외부 전송의
    근거로 받는다(11/13 실측: Sentry DSN 줄을 받지 않았다). 시험 파일은 그대로 받지 않는다."""
    (tmp_path / "sentry.client.config.ts").write_text(
        'Sentry.init({\n  dsn: "https://abc123@o45.ingest.us.sentry.io/45",\n  replaysSessionSampleRate: 0.1,\n});\n'
    )
    (tmp_path / "vite.config.ts").write_text('export default { server: { proxy: { host: "api.example.co.kr" } } };\n')
    _repo(tmp_path)
    cites = [
        {"file": "sentry.client.config.ts", "line": 2, "text": 'dsn: "https://abc123@o45.ingest.us.sentry.io/45",'},
        {"file": "sentry.client.config.ts", "line": 3, "text": "replaysSessionSampleRate: 0.1,"},
        {"file": "vite.config.ts", "line": 1, "text": 'host: "api.example.co.kr"'},
        TEST_LINE,
    ]
    cites.append({"file": "src/styles/../routes/signup.ts", "line": 4, "text": SIGNUP["text"]})  # 없는 폴더를 거친다
    out = rv.check(tmp_path, cites)
    assert out[-1]["ok"] and out.pop()["file"] == "src/routes/signup.ts"
    assert [(c["ok"], c["why"]) for c in out] == [
        (True, "config-value"),
        (False, "test-file"),
        (True, "config-value"),
        (False, "test-file"),
    ]


def _flip(status: str, cites: list, **said) -> dict:
    return {"duty": "x", "result": "뒤집음", "status": status, "citations": cites, "searches": [], **said}


def test_a_relabelled_guess_cannot_raise_an_item_the_guess_gate_moved(tmp_path):
    """자유 입력 관문이 '걸리지 않는 것으로 보임'으로 옮긴 항목은 반박이 표시만 바꿔 다시 올리지 못한다(11/13 실측:
    유튜브 검색 재생을 '자유 입력 추측'으로 옮긴 것을 반박이 '입력란·처리·저장'으로 바꿔 달고 '모름'으로 다시 올렸다).
    올리려면 그 정보를 받는 입력란·필드·저장 코드의 인용이 관문을 통과하고 applies 가 '예'여야 한다."""
    root = _repo(tmp_path)
    d = _duty("pipa-23-1")
    guessed = rv.said({"applies": "예", "condition": "채팅에 쓸 수 있다", "trigger": "자유 입력 추측"})
    ok = [{"file": "a.ts", "line": 1, "text": "x", "ok": True, "why": "grounded"}]
    status, gate = rv.accept(d, guessed, "seen-in-code", ok, False, None)
    f = {"status": status, "gate": gate}
    assert status == "likely-not-applicable" and gate["why"] == "free-input"
    relabel = _flip("확인할 것(해당 여부)", [STORE], applies="모름", trigger="입력란·처리·저장")
    out = rv.judge_rebut(root, d, relabel, f, None, None, False)
    assert out["result"] == "overturn-ungrounded" and out["gate"]["why"] == "free-input"
    fake = _flip("확인할 것(코드에서 본 것)", [FAKE], applies="예", trigger="입력란·처리·저장")
    assert rv.judge_rebut(root, d, fake, f, None, None, False)["result"] == "overturn-ungrounded"
    field = _flip("확인할 것(코드에서 본 것)", [STORE], applies="예", trigger="입력란·처리·저장")
    out = rv.judge_rebut(root, d, field, f, None, None, False)
    assert out["result"] == "overturned" and out["status"] == "seen-in-code"
    # 관문이 옮기지 않은 빼는 답은 지금처럼 뒤집을 수 있다
    plain = {"status": "likely-not-applicable", "gate": None}
    assert rv.judge_rebut(root, d, relabel, plain, None, None, False)["status"] == "check-applicability"

    # 반박 질문에 그 조건을 적는다
    def guessing(_duty_id):
        return ("확인할 것(코드에서 본 것)", [STORE], [], {"applies": "예", "trigger": "자유 입력 추측"})

    _, log = _run(root, "duty", use_static=False, investigator=fake_investigator(guessing))
    assert any("자유 입력 추측뿐이었다" in p for p in log)


def test_a_prohibition_is_seen_in_code_only_with_the_prohibited_act(tmp_path):
    """금지 의무("~하지 말 것")는 금지된 행위 자체를 인용할 때만 '코드에서 본 것'이다. 막는 장치가 없다는 것은 근거가
    아니고, 금지된 행위를 찾지 못하면 '걸리지 않는 것으로 보임'(검색이 맞으면 '해당 없음')이다(11/13 실측: 가짜 마감
    타이머·'반품 불가' 문구를 찾지 못하고도 "막는 장치가 없다"며 '코드에서 본 것'으로 뒀다)."""
    rows = {d["id"]: d for d in rv.load_duties()}
    banned = {i for i, d in rows.items() if d["prohibition"]}
    assert {"fla-3-1-h2", "ecom-21-1-h1-withdraw", "ecom-18-9"} <= banned
    assert not banned & set(rv._whenever()) and all(rows[i]["review_candidate"] or rows[i]["krcore"] for i in banned)
    assert "금지 의무" in P.duty_block(rows["fla-3-1-h2"]) and "금지 의무" not in P.duty_block(rows["tcra-3-2"])
    ok = [{"file": "a.ts", "line": 1, "text": "x", "ok": True, "why": "grounded"}]
    d = rows["fla-3-1-h2"]
    no_guard = rv.said({"applies": "예", "condition": "상품을 판다", "missing": "기만 표시를 막는 장치가 없음"})
    status, gate = rv.accept(d, no_guard, "seen-in-code", ok, True, None)
    assert status == "not-applicable" and gate["why"] == "prohibition" and "근거가" in gate["note"]
    assert rv.accept(d, no_guard, "seen-in-code", ok, False, None)[0] == "likely-not-applicable"
    act = rv.said({"applies": "예", "condition": "가짜 마감 타이머를 보인다", "shows": "금지 행위"})
    assert rv.accept(d, act, "seen-in-code", ok, False, None) == ("seen-in-code", None)
    assert rv.accept(d, rv.said({"applies": "모름"}), "seen-in-code", ok, False, None)[0] == "check-applicability"
    assert rv.accept(rows["tcra-3-2"], no_guard, "seen-in-code", ok, False, None) == ("seen-in-code", None)

    # 반박도 금지된 행위 자체를 인용해야 빼는 답을 깬다
    root, f = _repo(tmp_path), {"status": "not-applicable", "gate": None}
    out = rv.judge_rebut(root, d, _flip("확인할 것(코드에서 본 것)", [STORE], applies="예"), f, None, None, False)
    assert out["result"] == "overturn-ungrounded" and out["gate"]["why"] == "prohibition"
    shown = _flip("확인할 것(코드에서 본 것)", [STORE], applies="예", shows="금지 행위")
    assert rv.judge_rebut(root, d, shown, f, None, None, False)["result"] == "overturned"
    assert all("금지 행위" in t for t in (P.ACT, P.INVESTIGATE, P.REBUT))


def test_the_same_model_cannot_raise_an_item_to_evidence_found(tmp_path):
    """조사와 반박이 같은 모델이면 반박이 '충족'으로 올리는 뒤집기는 받지 않는다(11/13 실측: haiku 반박이 약관의 면책
    한 줄 "AI 결과에는 오류가 있을 수 있습니다"로 AI 사전 고지를 충족으로 올렸다). 면책 한 줄은 행위가 아니라는 예를
    준다."""
    root, d = _repo(tmp_path), _duty("aiact-31-1")
    f = {"status": "seen-in-code", "gate": None}
    up = _flip("충족 근거 있음", [STORE], applies="예", shows="행위")
    out = rv.judge_rebut(root, d, up, f, None, None, True)
    assert out["result"] == "overturn-ungrounded" and out["gate"]["why"] == "same-model"
    assert rv.judge_rebut(root, d, up, f, None, None, False)["result"] == "overturned"
    assert "오류가 있을 수 있습니다" in P.ACT

    # 전체 경로: 같은 모델의 반박은 충족으로 올리지 못하고, 다른 뒤집기(해당 없음 등)는 그대로다
    log: list = []
    doc, _ = _run(root, "duty", use_static=False, checker=fake_checker(log))
    same = rv.review(
        root,
        AgentJudge("claude-haiku-5-5", fake_investigator()),
        AgentJudge("claude-haiku-5-5", fake_checker([])),
        rv.Limits(usd=5.0, seconds=300, concurrency=2, batch="duty"),
        use_static=False,
    )
    _valid(same)
    flips = [i for i in doc["checklist"] if i["verification"]["result"] == "overturned"]
    raised = [i for i in flips if i["status"] == "evidence-found"]
    held = [i for i in same["checklist"] if (i["verification"].get("gate") or {}).get("why") == "same-model"]
    assert raised and {i["duty"] for i in held} == {i["duty"] for i in raised}
    assert all(i["status"] != "evidence-found" for i in held)


def test_the_rebuttal_can_be_turned_off_and_the_report_says_so(tmp_path):
    """반박을 끄면 묻지 않는다. 결과에 남는다: run.rebut false, models.verify none, 반박할 항목의 verification 은
    not-run(why rebut-off). 기본은 켬(웹이 쓰는 값)이다."""
    assert rv.Limits().rebut
    log: list = []
    doc = rv.review(
        _repo(tmp_path),
        AgentJudge("claude-haiku-5-5", fake_investigator()),
        AgentJudge("claude-sonnet-5-5", fake_checker(log)),
        rv.Limits(usd=5.0, seconds=300, concurrency=2, batch="duty", rebut=False),
        use_static=False,
    )
    _valid(doc)
    assert not log and not any(q["stage"] == "rebut" for q in doc["run"]["questions"])
    assert doc["run"]["rebut"] is False and doc["run"]["models"]["verify"] == "none"
    asked = [i for i in doc["checklist"] if i["first"] and i["status"] in (*rv.DROPS, *rv.TO_CHECK)]
    assert asked and all(i["verification"] == {"result": "not-run", "why": "rebut-off"} for i in asked)
    from policypack.cli import build_parser

    assert build_parser().parse_args(["review", ".", "--no-rebut"]).no_rebut
    assert not build_parser().parse_args(["review", "."]).no_rebut
