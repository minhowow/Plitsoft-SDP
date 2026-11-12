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
    assert [n["id"] for n in doc["data_flow"]["nodes"]] == ["n1", "n2", "n3"]
    assert [(e["from"], e["to"]) for e in doc["data_flow"]["edges"]] == [("n1", "n2")]

    items = doc["checklist"]
    firsts = [i["first"] for i in items if i["first"]]
    live = {fid for fid, f in feats.items() if "removed" not in f}
    whenever = rv._whenever()
    # 받는 조건: 시험 파일·지어낸 인용은 코드에서 본 것·충족이 되지 못하고, 검색 줄 수가 다른 해당 없음은 '보임'으로
    # 남는다. 그 기능이 있으면 걸리는 의무(가입의 약관 고지, AI 고지)는 해당 없음이 되지 못한다
    for i in items:
        f = i["first"]
        if not f:
            continue
        ok = any(c["ok"] for c in f["citations"])
        proven = bool(f["searches"]) and all(s["ok"] for s in f["searches"])
        if f["answered"] in ("evidence-found", "seen-in-code"):
            assert f["status"] == (f["answered"] if ok else "check-outside")
        if f["answered"] == "not-applicable":
            if whenever.get(i["duty"]) in live:
                assert f["status"] == "seen-in-code" and f["gate"]["why"] == "condition-present"
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

    # 반박: 해당 여부는 묻지 않고, 뒤집기는 인용·검색 조건을 넘은 것만
    for i in items:
        if i["status"] == "check-applicability":
            assert i["verification"] == {"result": "not-run", "why": "business-judgment"}
    flipped = [i for i in items if i["verification"]["result"] == "overturned"]
    assert flipped
    for i in flipped:
        before = i["first"]["status"]
        if before in rv.DROPS:
            assert i["status"] == "seen-in-code"
        elif before == "seen-in-code":
            assert i["status"] == "evidence-found" and i["verification"]["shows"] == "행위"
        else:
            assert i["status"] == "not-applicable" and i["verification"]["off_quote"] and i["searches"][0]["ok"]
            assert whenever.get(i["duty"]) not in live
    # 반박이 해당 없음으로 뒤집으려 해도 같은 관문(그 기능이 있으면 걸리는 의무는 받지 않는다)
    for i in items:
        v = i["verification"]
        if v["result"] == "overturn-ungrounded" and v.get("status") == "not-applicable":
            assert whenever.get(i["duty"]) in live and v["gate"]["why"] == "condition-present"
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
    live = {f["id"] for f in doc["profile"]["features"] if "removed" not in f}
    whenever = rv._whenever()
    for i in doc["checklist"]:
        if not i["asked"]:
            continue
        if whenever.get(i["duty"]) in live:
            assert i["first"]["status"] == "seen-in-code", i["duty"]
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
    assert all(i["status"] == "seen-in-code" and i["verification"]["gate"] is None for i in sure)
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
