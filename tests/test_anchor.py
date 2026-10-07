"""scope: anchor — 함수 단위 판정.

지켜야 할 것.
1. file 이 기본이고, file 규칙만 있으면 함수 경계 규칙을 컴파일하지 않는다.
2. anchor 가 경고한 집합은 file 이 경고한 집합을 포함해야 한다. 구역은 대안을 좁히기만 한다
   — 경고를 올리기만 하므로 방향성 신뢰와 맞는다.
   판정자에게는 그 구역만 보내고 구역마다 묻는다. 그래서 이 성질은 구조가 아니라 **판정자가 볼 것을
   빠뜨리지 않는 것**에 달려 있다. 적용 질문은 파일 단위로 묻고, 구역 프롬프트에는 같은 파일에서 구역이
   쓰는 선언의 본문·구역을 부르는 줄·this 필드 대입을 싣는다. 보이는 것만으로 답하는 흉내
   판정자(SeesOnlyThePrompt)로 이것을 확인한다. 답이 코드와 무관한 FakeJudge 로는 잡히지 않는다.
3. 차이는 함수가 여럿인 파일에서 난다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from policypack.evaluate.engine import Target, Unit, evaluate
from policypack.judge.fake import FakeJudge
from policypack.model import Rule
from policypack.pack.loader import find_anchor_without_regions, load_pack
from policypack.static.backend import Pos, PredicateKey, Span, StaticResult
from policypack.static.compile import compile_static
from policypack.static.parse import parse_semgrep_json
from policypack.static.semgrep_cli import SemgrepBackend

REPO = Path(__file__).resolve().parents[1]
KR_CORE = REPO / "policies" / "kr-core"
PROBES = REPO / "tests" / "data" / "anchor"

#: kr-core 세 규칙을 함수 단위로 잴 때 판정 위치로 쓸 applies-when 조건. 팩에서는 야간 광고 규칙만 함수 단위다.
ANCHOR_ON = {
    "signup-without-guard": "signup-context",
    "ad-send-without-night-guard": "send-call",
    "ai-output-without-label": "renders-jsx",
}


def anchored(pack):
    """ANCHOR_ON 의 규칙을 scope: anchor 로 바꾼 사본. 검증을 거쳐 만든다."""

    def convert(r):
        if r.id not in ANCHOR_ON:
            return r
        raw = {**r.model_dump(by_alias=True, exclude_none=True), "scope": "anchor", "anchor-on": ANCHOR_ON[r.id]}
        return Rule.model_validate(raw)

    policies = [pol.model_copy(update={"rules": [convert(r) for r in pol.rules]}) for pol in pack.policies]
    return pack.model_copy(update={"policies": policies})


def flagged(res) -> set[str]:
    return {f.case or f.file for f in res.findings if f.outcome.is_finding}


def file_scoped(pack):
    """모든 규칙을 scope: file 로 되돌린 사본. 내장 팩의 야간 광고 규칙이 함수 단위라 file 기준을 따로 만든다."""

    def convert(r):
        raw = r.model_dump(by_alias=True, exclude_none=True)
        raw.pop("scope", None)
        raw.pop("anchor-on", None)
        return Rule.model_validate(raw)

    policies = [pol.model_copy(update={"rules": [convert(r) for r in pol.rules]}) for pol in pack.policies]
    return pack.model_copy(update={"policies": policies})


@pytest.fixture(scope="module")
def kr():
    return file_scoped(load_pack(KR_CORE))


# ── 문법 ────────────────────────────────────────────────────────────────────

RULE = {
    "id": "r",
    "applies-when": [{"id": "send", "static": {"pattern": "$X.send(...)"}}],
    "compliant-if-any": [{"id": "guard", "static": {"pattern": "if ($H >= 21) { ... }"}}],
}


def test_anchor_needs_anchor_on():
    with pytest.raises(ValidationError, match="anchor-on 이 필요합니다"):
        Rule.model_validate({**RULE, "scope": "anchor"})


def test_anchor_on_must_name_an_applies_when_predicate():
    with pytest.raises(ValidationError, match="applies-when 에 없습니다"):
        Rule.model_validate({**RULE, "scope": "anchor", "anchor-on": "guard"})


def test_anchor_on_is_refused_on_a_file_rule():
    """file 에서는 읽히지 않는 설정이다. 적어 두면 동작하는 줄 안다."""
    with pytest.raises(ValidationError, match="scope: anchor 에서만"):
        Rule.model_validate({**RULE, "anchor-on": "send"})


def test_languages_without_function_boundaries_are_surfaced(kr):
    """함수 경계 패턴이 없는 언어는 파일 전체를 한 구역으로 판정한다. validate 가 알린다."""
    pack = anchored(kr)
    pol = pack.policies[0]
    rule = pol.rules[0].model_copy(update={"languages": ["python"]})
    pack = pack.model_copy(update={"policies": [pol.model_copy(update={"rules": [rule]}), *pack.policies[1:]]})
    assert any("python" in w for w in find_anchor_without_regions(pack))
    assert find_anchor_without_regions(anchored(kr)) == []


# ── file 은 그대로 ──────────────────────────────────────────────────────────


def test_file_scope_compiles_no_region_rules(kr):
    """함수 경계 규칙이 붙으면 semgrep 설정과 시간 초과 계산이 바뀐다. file 팩에는 없어야 한다."""
    assert not any(r["id"].startswith("policypack-region") for r in compile_static(kr)["rules"])
    assert any(r["id"].startswith("policypack-region") for r in compile_static(anchored(kr))["rules"])


# ── 함수 경계는 필요한 파일에서만 구한다 ────────────────────────────────────


def test_function_boundaries_are_computed_only_where_a_function_rule_can_apply():
    """경계 규칙은 모든 함수에 맞는다. 모든 파일에 돌리면 광고 발송이 없는 파일까지 2~3배 느려지고, 함수가 수천
    개인 파일은 매치 상한을 넘겨 정책 조건의 매치까지 버려졌다(검토에서 실측). 함수 단위 규칙이 걸릴 수 있는
    파일에서만 두 번째 실행으로 구한다."""
    pack = load_pack(KR_CORE)
    signup = KR_CORE / "tests" / "pipa-22-2" / "violating.ts"
    ads = KR_CORE / "tests" / "network-act-50-3" / "two-sends-one-guarded.ts"

    alone = SemgrepBackend().run(compile_static(pack), [signup])
    assert alone.runs == 1 and alone.regions == {}

    both = SemgrepBackend().run(compile_static(pack), [signup, ads])
    assert both.runs == 2
    assert {p.resolve() for p in both.regions} == {ads.resolve()}


def test_choosing_files_for_function_boundaries():
    from policypack.static.backend import Match
    from policypack.static.semgrep_cli import region_targets

    def rule(pred, role=None):
        meta = {"policy": "p", "rule": "r", "group": "applies-when", "predicate": pred}
        return {"id": f"p.r.{pred}", "metadata": {"policypack": {**meta, **({"anchor": role} if role else {})}}}

    on, wth = PredicateKey("p", "r", "applies-when", "send"), PredicateKey("p", "r", "applies-when", "ad")
    span = Span(Pos(1, 1, 0), Pos(1, 5, 4))
    a, b, c, d = (Path(f"/t/{n}.ts") for n in "abcd")
    result = StaticResult(
        matches=[Match(on, a, span), Match(wth, a, span), Match(on, b, span), Match(on, c, span), Match(wth, d, span)],
        partial_unparsed={c: []},
    )
    rules = [rule("send", "on"), rule("ad", "with")]
    # a: 두 조건이 다 맞았다. b: 판정 위치만 맞았다(규칙이 적용되지 않는다). c: 일부가 파싱되지 않아 다른 조건의
    # '매치 없음'을 믿을 수 없다. d: 판정 위치가 없다(함수 경계가 있어도 쓸 데가 없다)
    assert region_targets(rules, result, [a, b, c, d]) == [a, c]
    # 표지가 없는 설정(직접 쓴 시험용 설정)은 전부 고른다
    assert region_targets([rule("send"), rule("ad")], result, [a, b]) == [a, b]


def test_boundaries_where_needed_give_the_same_verdicts_as_boundaries_everywhere(monkeypatch, kr):
    """두 번에 나눠 돌려도 판정은 같다. 모든 파일에서 경계를 구하던 방식과 견준다."""
    import policypack.static.semgrep_cli as cli_backend

    pack = anchored(kr)
    files = sorted(PROBES.iterdir()) + sorted((KR_CORE / "tests" / "network-act-50-3").iterdir())
    targets = [Target(path=f, lang="typescript", case=f.name) for f in files]

    def verdicts():
        static = SemgrepBackend().run(compile_static(pack), [t.path for t in targets])
        res = evaluate(pack, targets, static, judge=FakeJudge("아니오"))
        return sorted((f.case, f.ref, f.outcome.value, f.line, f.region, tuple(f.anchor_lines)) for f in res.findings)

    narrow = verdicts()
    monkeypatch.setattr(cli_backend, "region_targets", lambda rules, result, targets: list(targets))
    assert narrow and narrow == verdicts()


# ── 함수가 여럿인 파일 ──────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def probes(kr):
    files = sorted(PROBES.iterdir())
    targets = [Target(path=f, lang="typescript", case=f.name) for f in files]
    out = {}
    for scope, pack in (("file", kr), ("anchor", anchored(kr))):
        static = SemgrepBackend().run(compile_static(pack), [t.path for t in targets])
        out[scope] = evaluate(pack, targets, static, judge=FakeJudge("아니오"))
    return out


NARROWED = ("signup-without-guard", "ad-send-without-night-guard")


def test_file_scope_lets_a_second_unguarded_function_through(probes):
    """가드가 파일 어딘가에 있으면 file 은 통과시킨다. 같은 파일의 다른 발송 함수는 가드가 없다."""
    assert not {f.case for f in probes["file"].findings if f.rule in NARROWED}


def test_anchor_flags_the_unguarded_function(probes):
    night = [f for f in probes["anchor"].findings if f.case == "ads-mixed.tsx"]
    assert [(f.rule, f.region, f.anchor_lines) for f in night] == [("ad-send-without-night-guard", (7, 10), [8, 9])]


def test_anchor_limits_are_recorded_honestly(probes):
    """구역 밖의 가드는 보지 못한다. 경고를 올리는 방향의 오류라 방향성 신뢰는 지키지만 오탐이다.
    cron 이 함수 이름을 참조하는 경우와, 가드가 다른 함수(헬퍼)에 있는 경우."""
    assert {"ads-schedule-ref.ts", "child-helper.ts"} <= flagged(probes["anchor"])


def test_anchor_flags_a_superset_of_file(probes):
    assert flagged(probes["file"]) <= flagged(probes["anchor"])


def test_ai_citation_outside_the_region_cannot_clear(tmp_path, kr):
    """판정자가 다른 함수의 가드를 인용하면, 그 구역의 경고는 풀리지 않는다."""
    f = _one(tmp_path, "ads.tsx", (PROBES / "ads-mixed.tsx").read_text(encoding="utf-8"))
    pack = anchored(kr)
    static = SemgrepBackend().run(compile_static(pack), [f])

    class CitesTheOtherGuard:
        id = "stub"

        def ask(self, q):
            from policypack.judge.base import Answer

            return Answer(raw="예", evidence="if (h >= 21 || h < 8) { return; }")

    res = evaluate(pack, [Target(path=f, lang="typescript", case="ads")], static, judge=CitesTheOtherGuard())
    ads = [x for x in res.findings if x.rule == "ad-send-without-night-guard"]
    # 관문이 받지 않은 '예'는 판정에 넣지 않는다. 판정자가 없을 때와 같은 확실한 경고이고 까닭을 남긴다
    assert [(x.region, x.outcome.value) for x in ads] == [((7, 10), "needs-review")]
    assert any("판정 구역 밖" in t for t in ads[0].trace)
    assert "citation-rejected" in [r.value for r in ads[0].untested_reasons]


def test_questions_are_asked_per_region(probes):
    """함수 단위면 같은 파일의 두 함수가 따로 판정 단위가 된다. 판정자는 구역마다 따로 답한다."""
    res = probes["anchor"]
    units = [u for u in res.units if u.target.case == "ads-mixed.tsx" and "ad-send" in u.rule.id]
    assert len(units) == 2


def _two_function_file(tmp_path):
    return _one(
        tmp_path,
        "two.ts",
        'import { sms } from "./sms";\n'
        "const OPEN_HOUR = 9;\n"
        "const UNUSED_BANNER = 1;\n"
        "\n"
        "export async function sendNight(users) {\n"
        '  for (const u of users) await sms.send({ to: u.phone, text: "(광고) 심야" });\n'
        "}\n"
        "\n"
        "export async function sendDay(users) {\n"
        "  if (new Date().getHours() < OPEN_HOUR) return;\n"
        '  for (const u of users) await sms.send({ to: u.phone, text: "(광고) 주간" });\n'
        "}\n",
    )


def test_judge_sees_only_its_region_and_the_file_header(tmp_path, kr):
    """함수 단위 판정의 프롬프트에는 그 함수와 같은 파일의 머리(그 함수가 쓰는 import·최상위 선언)만
    들어간다. 다른 함수의 코드와 쓰이지 않은 선언은 들어가지 않는다."""
    f = _two_function_file(tmp_path)
    pack = anchored(kr)
    static = SemgrepBackend().run(compile_static(pack), [f])
    judge = FakeJudge("아니오")
    evaluate(pack, [Target(path=f, lang="typescript")], static, judge=judge)
    asked = [q for q in judge.asked if q.rule == "ad-send-without-night-guard"]
    codes = {q.code.strip().splitlines()[0]: q for q in asked}
    night = codes["export async function sendNight(users) {"]
    day = codes["export async function sendDay(users) {"]
    assert "sendDay" not in night.code and "OPEN_HOUR" not in night.code
    assert "sendNight" not in day.code
    assert 'import { sms } from "./sms";' in day.header and "const OPEN_HOUR = 9;" in day.header
    assert "UNUSED_BANNER" not in day.header and "UNUSED_BANNER" not in night.header
    assert "import { sms }" in night.prompt() and "판정 대상이 아니다" in night.prompt()


def test_file_scope_still_sends_the_whole_file(tmp_path, kr):
    """파일 단위 판정은 파일 전체를 보내고 머리·조각 표시가 없다."""
    f = _two_function_file(tmp_path)
    static = SemgrepBackend().run(compile_static(kr), [f])
    judge = FakeJudge("아니오")
    evaluate(kr, [Target(path=f, lang="typescript")], static, judge=judge)
    assert judge.asked
    for q in judge.asked:
        assert q.code == f.read_text(encoding="utf-8") and q.header == "" and q.fragment == ""


def test_one_citation_per_region_can_clear_each_region(tmp_path, kr):
    """구역마다 묻고, 각 구역의 줄을 인용한 '예'가 그 구역을 푼다."""
    f = _two_function_file(tmp_path)
    pack = anchored(kr)
    static = SemgrepBackend().run(compile_static(pack), [f])
    res = evaluate(pack, [Target(path=f, lang="typescript")], static, judge=FakeJudge("예", echo_first_line=True))
    assert [x.region for x in res.findings if x.rule == "ad-send-without-night-guard"] == []


def test_a_header_citation_cannot_clear(tmp_path, kr):
    """머리는 참고다. 머리의 줄을 인용한 '예'는 구역을 풀지 못한다(근거 관문은 구역만 본다)."""
    f = _two_function_file(tmp_path)
    pack = anchored(kr)
    static = SemgrepBackend().run(compile_static(pack), [f])
    judge = FakeJudge("예", evidence="const OPEN_HOUR = 9;")
    res = evaluate(pack, [Target(path=f, lang="typescript")], static, judge=judge)
    ads = [x for x in res.findings if x.rule == "ad-send-without-night-guard"]
    assert ads and all(x.outcome.value == "needs-review" for x in ads)
    assert all(any("판정 구역 밖" in t for t in x.trace) for x in ads)


def test_top_level_region_sends_no_function_bodies(tmp_path, kr):
    f = _one(
        tmp_path,
        "top2.ts",
        "export async function sendDay(users) {\n"
        "  const secretGuard = 1;\n"
        '  for (const u of users) await sms.send({ to: u.phone, text: "(광고) 주간" });\n'
        "}\n\n"
        'await sms.send({ to: ADMIN, text: "(광고) 오픈 기념" });\n',
    )
    pack = anchored(kr)
    static = SemgrepBackend().run(compile_static(pack), [f])
    judge = FakeJudge("아니오")
    evaluate(pack, [Target(path=f, lang="typescript")], static, judge=judge)
    top = [q for q in judge.asked if q.rule == "ad-send-without-night-guard" and "ADMIN" in q.code]
    assert top and all("secretGuard" not in q.code and q.header == "" for q in top)
    assert all(q.fragment == "top-level" and "함수 본문은 비웠다" in q.prompt() for q in top)


class SeesOnlyThePrompt:
    """프롬프트에 보이는 것만으로 답하는 흉내 판정자. 실제 모델이 이렇게 답한다는 뜻이 아니다.
    구역 프롬프트가 판정에 필요한 것을 빠뜨리면 판정이 file 과 달라진다는 것을 보이는 장치다.

    - 적용 질문: 프롬프트에 birth 가 보이면 '예'.
    - 대안 질문: 코드에 `if (` 줄이 있고, 그 가드가 아무것도 하지 않는다는 것(`return false`)이
      프롬프트 어디에도 보이지 않으면 그 줄을 인용해 '예'."""

    id = "sees"

    def __init__(self):
        self.asked = []

    def ask(self, q):
        from policypack.judge.base import Answer

        self.asked.append(q)
        seen = q.prompt()
        if q.predicate == "applies-ai":
            return Answer(raw="예" if re.search(r"\bbirth\b", seen) else "아니오")
        guard = next((ln.strip() for ln in q.code.splitlines() if ln.strip().startswith("if (")), "")
        if guard and "return false" not in seen:
            return Answer(raw="예", evidence=guard)
        return Answer(raw="아니오")


FAKE_GUARD = (
    'import { sms } from "./sms";\n'
    "\n"
    "function isQuietHours(now: Date): boolean {\n"
    "  // 야간(21~8시)에는 광고를 보내지 않는다\n"
    "  return false;\n"
    "}\n"
    "\n"
    "export async function sendPromo(users) {\n"
    "  if (isQuietHours(new Date())) return;\n"
    '  for (const u of users) await sms.send({ to: u.phone, text: "(광고) 주말 할인" });\n'
    "}\n"
)

BIRTH_ELSEWHERE = (
    'import { db } from "./db";\n'
    "\n"
    "function parseForm(body) {\n"
    "  const birth = body.birth;\n"
    "  return { name: body.name, birth };\n"
    "}\n"
    "\n"
    "export async function signupHandler(req) {\n"
    "  const form = parseForm(req.body);\n"
    "  await db.users.insert(form);\n"
    "}\n"
)


def _static_with_unknown_applicability(pack, f):
    """적용 조건 birth-or-age 를 엔진이 끝내지 못한 것으로 만든다. 적용이 '모름'이 되어 적용 질문을 묻는다.
    고정한 판정 방식에서 적용 질문은 정적 적용 판단이 '모름'일 때만 나간다."""
    static = SemgrepBackend().run(compile_static(pack), [f])
    key = PredicateKey("kr.pipa.22-2", "signup-without-guard", "applies-when", "birth-or-age")
    static.matches = [m for m in static.matches if m.key != key]
    static.predicate_timeouts[f] = [key]
    return static


def test_anchor_keeps_file_warnings_when_the_helper_body_is_fake(tmp_path, kr):
    """머리에 `function isQuietHours(...) {` 첫 줄만 실리면 판정자가 가짜 가드를 믿어 anchor 가 file 의
    경고를 없앴다. 헬퍼 본문이 머리에 실리면 보이는 것만으로 답하는 판정자에게도 경고가 남는다."""
    f = _one(tmp_path, "fake-guard.ts", FAKE_GUARD)
    out = {}
    for scope, pack in (("file", kr), ("anchor", anchored(kr))):
        static = SemgrepBackend().run(compile_static(pack), [f])
        res = evaluate(pack, [Target(path=f, lang="typescript")], static, judge=SeesOnlyThePrompt())
        out[scope] = [x.outcome.value for x in res.findings if x.rule == "ad-send-without-night-guard"]
    assert out == {"file": ["needs-review"], "anchor": ["needs-review"]}


def test_anchor_keeps_file_warnings_when_applicability_is_elsewhere_in_the_file(tmp_path, kr):
    """적용 질문을 구역만 보고 물으면, 생년월일이 다른 함수에 있을 때 '아니오'로 규칙이 꺼졌다."""
    f = _one(tmp_path, "birth-elsewhere.ts", BIRTH_ELSEWHERE)
    out = {}
    for scope, pack in (("file", kr), ("anchor", anchored(kr))):
        static = _static_with_unknown_applicability(pack, f)
        judge = SeesOnlyThePrompt()
        res = evaluate(pack, [Target(path=f, lang="typescript")], static, judge=judge)
        out[scope] = [x.outcome.value for x in res.findings if x.rule == "signup-without-guard"]
        applies = [q for q in judge.asked if q.predicate == "applies-ai"]
        assert applies and all(q.code == BIRTH_ELSEWHERE and q.header == "" and q.fragment == "" for q in applies)
    assert out == {"file": ["needs-review"], "anchor": ["needs-review"]}


def test_the_seeing_judge_can_clear_a_real_guard(tmp_path, kr):
    """위 시험이 비지 않았다는 대조군. 헬퍼가 실제로 시간을 보면 두 단위 모두 푼다."""
    f = _one(tmp_path, "real-guard.ts", FAKE_GUARD.replace("return false;", "return now.getHours() >= 21;"))
    for pack in (kr, anchored(kr)):
        static = SemgrepBackend().run(compile_static(pack), [f])
        res = evaluate(pack, [Target(path=f, lang="typescript")], static, judge=SeesOnlyThePrompt())
        assert not [x for x in res.findings if x.rule == "ad-send-without-night-guard"]


def test_anchors_outside_every_function_send_the_whole_file_and_the_notice_says_so(tmp_path, kr):
    """앵커가 모두 함수 밖이면 구역이 파일 전체다(file 이 내는 단위를 anchor 가 없애지 않으려고).
    그러면 함수 본문도 간다. 고지가 이 경우를 말해야 한다."""
    from policypack.cli import _egress_notice

    src = (
        'import { sms } from "./sms";\n\n'
        "function internalSecret() {\n"
        '  return "sk-internal";\n'
        "}\n\n"
        'await sms.send({ to: "010", text: "(광고) 오픈" });\n'
    )
    f = _one(tmp_path, "toponly.ts", src)
    pack = anchored(kr)
    static = SemgrepBackend().run(compile_static(pack), [f])
    judge = FakeJudge("아니오")
    evaluate(pack, [Target(path=f, lang="typescript")], static, judge=judge)
    asked = [q for q in judge.asked if q.rule == "ad-send-without-night-guard"]
    assert asked and all(q.code == src and q.fragment == "" for q in asked)
    notice = _egress_notice("claude-cli:haiku", env={})
    assert "앵커가 함수 밖에만 있거나" in notice and "파일 전체" in notice
    assert "적용 여부를 AI에 묻는 질문은 파일 전체" in notice
    assert "함수 본문을 비운 모듈 최상위 줄" in notice


# ── 같은 파일 머리 ──────────────────────────────────────────────────────────


def _header(src: str, first: int, last: int) -> str:
    from policypack.evaluate.engine import file_header
    from policypack.evidence import strip_comments

    raw = src.split("\n")
    region = Span(Pos(first, 1, 0), Pos(last, 1, 0))
    return file_header(raw, region, "\n".join(raw[first - 1 : last]), strip_comments(src).split("\n"))


def test_header_does_not_swallow_code_after_a_semicolon_less_import():
    src = (
        'import { sms } from "./sms"\n'
        'import "dotenv/config"\n'
        "\n"
        "export async function guardedSend(users) {\n"
        "  if (new Date().getHours() >= 21) return\n"
        "  for (const u of users) await sms.send(u)\n"
        "}\n"
        "\n"
        "export async function nightSend(users) {\n"
        "  for (const u of users) await sms.send(u)\n"
        "}"
    )
    assert _header(src, 9, 11) == 'import { sms } from "./sms"'
    assert "nightSend" not in _header(src, 4, 7) and "getHours" not in _header(src, 4, 7)


def test_header_treats_non_declaration_imports_as_one_line():
    src = 'import fs = require("fs")\nimport("./polyfill").then(() => 1)\nimport.meta.env\n/*\nimport foo\n*/\n'
    src += "function f() {\n  return fs;\n}"
    assert _header(src, 7, 9) == 'import fs = require("fs")'


def test_header_folds_long_imports_and_keeps_used_declarations_first():
    """8줄 넘는 import 가 from 없이 잘렸고, 쓰이지 않는 import 가 상한을 먼저 채워 쓰인 상수가 빠졌다."""
    unused = "".join(f'import {{ u{i} }} from "m{i}";\n' for i in range(80))
    names = "".join(f"  Name{i},\n" for i in range(10))
    src = unused + "import {\n" + names + '} from "names";\nconst NIGHT_START = 21;\n\n'
    src += "export function send() {\n  if (h >= NIGHT_START) return;\n  Name9();\n}"
    first = src.split("\n").index("export function send() {") + 1
    header = _header(src, first, first + 3)
    assert header.splitlines() == [
        "import { " + " ".join(f"Name{i}," for i in range(10)) + ' } from "names";',
        "const NIGHT_START = 21;",
    ]


def test_header_shows_helper_bodies_callers_and_field_writes():
    """값이 어디서 오는지와 헬퍼가 실제로 무엇을 하는지. 구역만 보내면 이것이 사라졌다(검토)."""
    src = (
        'const path = require("path");\n'
        'const DOCS = path.join(__dirname, "docs");\n'
        "function isSafe(name) {\n"
        "  return false;\n"
        "}\n"
        "class Ctl {\n"
        "  start(sid, returnTo) {\n"
        "    this.pending.set(sid, returnTo);\n"
        "  }\n"
        "  readDoc(name) {\n"
        "    if (!isSafe(name)) return;\n"
        "    return fs.readFileSync(path.join(DOCS, this.pending.get(name)));\n"
        "  }\n"
        "}\n"
        'app.get("/doc", (req, res) => res.send(new Ctl().readDoc(req.query.name)));'
    )
    header = _header(src, 10, 13)
    assert "  return false;" in header  # 헬퍼 본문
    assert "this.pending.set(sid, returnTo);" in header  # this 필드에 값을 넣는 줄
    assert "readDoc(req.query.name)" in header  # 부르는 줄
    assert 'const DOCS = path.join(__dirname, "docs");' in header and 'require("path")' in header
    assert "fs.readFileSync" not in header  # 구역 자신은 머리에 없다


def test_header_shows_the_statement_an_anonymous_callback_belongs_to():
    """이름 없는 콜백은 부르는 줄을 찾을 수 없다. 값의 출처는 같은 문장의 앞줄에 있다(2026-09-27 시범의
    V08: file 이 readdirSync 에서 온다는 것이 안 보여 판정자가 '아니오'로 답했다)."""
    src = (
        'var fs = require("fs");\n'
        'var path = require("path");\n'
        "var db = {};\n"
        "\n"
        "fs\n"
        "  .readdirSync(__dirname)\n"
        "  .filter(function (file) {\n"
        '    return file !== "index.js";\n'
        "  })\n"
        "  .forEach(function (file) {\n"
        "    var model = sequelize.import(path.join(__dirname, file));\n"
        "  });\n"
    )
    header = _header(src, 10, 12).splitlines()
    chain = ["fs", "  .readdirSync(__dirname)", "  .filter(function (file) {"]
    chain += ['    return file !== "index.js";', "  })"]
    assert header[-5:] == chain
    assert 'var fs = require("fs");' in header  # 앞줄이 쓰는 이름의 import
    assert "var db = {};" not in header  # 앞 문장은 싣지 않는다


def test_header_shows_the_call_an_argument_callback_belongs_to():
    src = (
        'import { router } from "./r";\n\n'
        'router.post(\n  "/signup",\n  async (req, res) => {\n    save(req.body);\n  },\n);\n'
    )
    header = _header(src, 5, 7)
    assert header.splitlines()[-2:] == ["router.post(", '  "/signup",']


def test_named_functions_get_callers_not_statement_heads():
    src = "const x = 1;\nfunction send(u) {\n  mail(u);\n}\nsend(req.body.user);\n"
    assert _header(src, 2, 4) == "send(req.body.user);"


def test_header_body_is_capped_and_marked():
    body = "".join(f"  const x{i} = {i};\n" for i in range(30))
    src = "function helper() {\n" + body + "  return 1;\n}\n\nexport function g() {\n  return helper();\n}"
    first = src.split("\n").index("export function g() {") + 1
    header = _header(src, first, first + 2).splitlines()
    assert header[0] == "function helper() {" and header[-1] == "  // … (본문이 길어 줄였다)"
    assert len(header) == 13


# ── 줄 번호를 semgrep 과 같게 센다 ──────────────────────────────────────────


@pytest.mark.parametrize("sep", [" ", "\f", "\r"], ids=["U+2028", "formfeed", "lone-CR"])
def test_region_slice_counts_lines_like_semgrep(tmp_path, sep, kr):
    f = tmp_path / "a.ts"
    f.write_bytes(f'const s = "a{sep}b";\nexport function g() {{\n  return 1;\n}}\n'.encode())
    unit = Unit(
        policy=kr.policies[0],
        rule=kr.policies[0].rules[0],
        target=Target(path=f, lang="typescript"),
        region=Span(Pos(2, 1, 0), Pos(4, 2, 0)),
    )
    assert unit.gate_code().split("\n")[0] == "export function g() {"


def test_region_slice_on_crlf_files(tmp_path, kr):
    f = tmp_path / "a.ts"
    f.write_bytes(b"const s = 1;\r\nexport function g() {\r\n  return 1;\r\n}\r\n")
    unit = Unit(
        policy=kr.policies[0],
        rule=kr.policies[0].rules[0],
        target=Target(path=f, lang="typescript"),
        region=Span(Pos(2, 1, 0), Pos(4, 2, 0)),
    )
    assert unit.gate_code() == "export function g() {\n  return 1;\n}"


def test_region_rule_timeout_does_not_distrust_the_file():
    err = {"type": "Timeout", "rule_id": "policypack-region.typescript", "path": "/t/a.ts", "level": "warn"}
    res = parse_semgrep_json({"results": [], "errors": [err]})
    assert res.hard_unparsed == set()


def test_regions_merge_across_chunks():
    a, b = StaticResult(), StaticResult()
    b.regions[Path("/t/a.ts")] = [Span(Pos(1, 1, 0), Pos(3, 1, 9))]
    a.absorb(b)
    assert a.regions == b.regions


# ── 보고 ────────────────────────────────────────────────────────────────────


def test_sarif_points_at_the_anchor_and_carries_the_region(probes, kr):
    from policypack.report import sarif

    doc = sarif.build(probes["anchor"], anchored(kr), KR_CORE, PROBES)
    res = next(
        r
        for r in doc["runs"][0]["results"]
        if r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "ads-mixed.tsx"
    )
    loc = res["locations"][0]["physicalLocation"]
    assert loc["region"] == {"startLine": 8}
    assert loc["contextRegion"] == {"startLine": 7, "endLine": 10}
    assert [r["physicalLocation"]["region"]["startLine"] for r in res["relatedLocations"]] == [9]
    assert res["properties"]["scope"] == "anchor"


def test_file_findings_keep_their_sarif_shape(probes, kr):
    from policypack.report import sarif

    res = sarif.build(probes["file"], kr, KR_CORE, PROBES)["runs"][0]["results"]
    assert res
    for r in res:
        assert "contextRegion" not in r["locations"][0]["physicalLocation"] and "relatedLocations" not in r


def test_fingerprints_are_distinct_and_order_independent(tmp_path):
    """같은 조각의 판정 둘이 같은 지문이면 코드 스캐닝이 하나로 합친다."""
    from policypack.report.fingerprint import fingerprints
    from policypack.report.outcome import Finding, Outcome

    f = tmp_path / "a.ts"
    f.write_text("x\n" * 3, encoding="utf-8")

    def finding(region):
        return Finding(
            policy="p", rule="r", outcome=Outcome.NEEDS_REVIEW, file=str(f), line=2, scope="anchor", region=region
        )

    a, b = finding((1, 2)), finding((2, 3))
    one, two = fingerprints([a, b]), fingerprints([b, a])
    assert len(set(one)) == 2
    assert sorted(one) == sorted(two)


def test_json_carries_scope_and_region(probes):
    from policypack.report import json_out

    doc = json.loads(json_out.dumps(probes["anchor"], PROBES))
    night = next(f for f in doc["findings"] if f["file"] == "ads-mixed.tsx")
    assert night["scope"] == "anchor" and night["region"] == {"start_line": 7, "end_line": 10}
    assert night["anchor_lines"] == [8, 9]


# ── 검토 반영 ───────────────────────────────────────────────────────────────


def _one(tmp_path, name: str, src: str):
    f = tmp_path / name
    f.write_text(src, encoding="utf-8")
    return f


def test_comment_gate_counts_quotes_from_the_whole_file(tmp_path, kr):
    """근거 관문은 주석을 걷어 내고 인용을 찾는다. 구역 조각만 걷으면 앞쪽 JSX 글의 짝 없는
    따옴표(Don't)를 몰라 주석을 코드로 읽었고, anchor 가 file 이 경고한 것을 풀었다."""
    f = _one(
        tmp_path,
        "promo.tsx",
        "const footer = <small>Don't reply to this message</small>;\n\n"
        "export async function sendNight(users: User[]) {\n"
        "  const html = render(<Promo footer={footer}>We're open late</Promo>);\n"
        "  // if (h >= 21 || h < 8) { return; }   disabled for launch week\n"
        '  for (const u of users) await sms.send({ to: u.phone, text: "(광고) 심야 특가", html });\n'
        "}\n",
    )
    judge = FakeJudge("예", evidence="if (h >= 21 || h < 8) { return; }")
    target = [Target(path=f, lang="typescript")]
    out = {}
    for scope, pack in (("file", kr), ("anchor", anchored(kr))):
        static = SemgrepBackend().run(compile_static(pack), [f])
        res = evaluate(pack, target, static, judge=judge)
        out[scope] = {x.rule for x in res.findings if x.outcome.is_finding}
    assert "ad-send-without-night-guard" in out["file"], "시험이 비지 않았다: file 이 경고해야 한다"
    assert out["file"] <= out["anchor"]


def test_top_level_sends_are_judged_on_their_own_lines(tmp_path, kr):
    f = _one(
        tmp_path,
        "top.ts",
        "export async function sendDay(users) {\n"
        "  const h = new Date().getHours();\n"
        "  if (h >= 21 || h < 8) { return; }\n"
        '  for (const u of users) await sms.send({ to: u.phone, text: "(광고) 주간 특가" });\n'
        "}\n\n"
        'await sms.send({ to: ADMIN, text: "(광고) 오픈 기념" });\n',
    )
    pack = anchored(kr)
    static = SemgrepBackend().run(compile_static(pack), [f])
    res = evaluate(pack, [Target(path=f, lang="typescript")], static, judge=FakeJudge("아니오"))
    ads = [x for x in res.findings if x.rule == "ad-send-without-night-guard"]
    assert [(x.top_level, x.anchor_lines, x.outcome.value) for x in ads] == [(True, [7], "needs-review")]


def test_a_static_clearance_lists_only_the_matches_of_its_own_zone(tmp_path, kr):
    """함수 단위에서 풀린 기록의 줄은 그 구역의 매치뿐이다. 다른 함수나 함수 밖의 가드 줄을 싣지 않는다."""
    f = _one(
        tmp_path,
        "zones.ts",
        "export async function sendDay(users) {\n"
        "  const h = new Date().getHours();\n"
        "  if (h >= 21 || h < 8) { return; }\n"
        '  for (const u of users) await sms.send({ to: u.phone, text: "(광고) 주간 특가" });\n'
        "}\n\n"
        "const hour = new Date().getHours();\n"
        'if (hour >= 21 || hour < 8) { throw new Error("night"); }\n'
        'await sms.send({ to: ADMIN, text: "(광고) 오픈 기념" });\n',
    )
    pack = anchored(kr)
    static = SemgrepBackend().run(compile_static(pack), [f])
    res = evaluate(pack, [Target(path=f, lang="typescript")], static)
    got = [(c["line"], c["alternatives"]) for c in res.static_cleared if c["rule"] == "ad-send-without-night-guard"]
    assert got == [(4, [{"id": "night-hour-block", "lines": [3]}]), (9, [{"id": "night-hour-block", "lines": [8]}])]


def test_one_line_function_has_no_context_region(tmp_path, kr):
    from policypack.report import sarif

    f = _one(tmp_path, "one.ts", 'export const blast = (u) => sms.send({ to: u.phone, text: "(광고) 특가" });\n')
    pack = anchored(kr)
    static = SemgrepBackend().run(compile_static(pack), [f])
    res = evaluate(pack, [Target(path=f, lang="typescript")], static, judge=FakeJudge("아니오"))
    doc = sarif.build(res, pack, KR_CORE, tmp_path)
    [r] = [r for r in doc["runs"][0]["results"] if r["ruleId"] == "kr.network-act.50-3/ad-send-without-night-guard"]
    loc = r["locations"][0]["physicalLocation"]
    assert "contextRegion" not in loc and r["properties"]["scope"] == "anchor"
