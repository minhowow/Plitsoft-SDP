"""`policypack test` — 정책 작성자를 위한 단위 테스트.

정책을 새로 쓰면 세 가지를 보여야 한다. 위반 모양이 경고를 내는가, **적법한 대안마다** 그
대안 하나만으로 경고가 풀리는가, 그리고 혼자 풀 수 있는 정적 대안마다 그것을 흉내 내지만 풀리면
안 되는 코드(음성 픽스처, `decoy-for`)가 경고로 남는가. `semgrep --test` 가 규칙마다 `ruleid:`/`ok:`
픽스처를 두는 것과 같은 자리다. 약한 대안은 AI 확인 없이 경고를 풀지 못하므로 '혼자 풀기'를
요구하지 않는다.

## 픽스처는 손대지 않은 코드, 기대는 옆 파일에

    policies/kr-core/
      pack.yaml
      tests/
        pipa-22-2.test.yaml        # 기대 판정과 AI 답 스텁
        pipa-22-2/violating.ts     # 픽스처: 실제 코드 그대로

`// ruleid:` 같은 주석 방식은 실측으로 기각했다. 우리 정규식 조건이 주석 글자를 읽는다.
`// ok: kr.pipa.22-2/signup-without-guard` 의 'signup' 이 가입 조건에 매치해 바로 그
경고를 만들었고, 한국어 기대 주석 한 줄이 'AI 생성' 표시 문구 조건을 참으로 만들어
위반을 가렸다.

## AI 조건은 스텁으로

픽스처에 "판정자가 이렇게 답했다고 치자"를 적는다. 근거 관문은 엔진이 평소처럼
적용한다. 그래서 스텁도 방향성 신뢰를 우회하지 못한다 — 코드에 없는 줄을 인용한 '예'는
'모름'이 되어 경고가 남는다. 답을 적지 않은 AI 질문은 판정이 기대와 맞아도 실패다.
모델은 부르지 않는다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from pydantic import Field, ValidationError, field_validator, model_validator
from ruamel.yaml import YAML, YAMLError

from policypack.discover import engine_skips, language_of, not_utf8
from policypack.errors import ConfigError, PackError
from policypack.evaluate.engine import EvalResult, Target, Unit, evaluate, static_value
from policypack.evaluate.kleene import FALSE, TRUE, or3
from policypack.evaluate.planner import considered_values, needs_alternative_questions
from policypack.judge.base import Answer, Question
from policypack.model import PolicyPack, Predicate, _Base
from policypack.static.backend import PredicateKey
from policypack.static.compile import GROUP_APPLIES, compile_static

TEST_API = "policypack/test-0.1"
_yaml = YAML(typ="safe", pure=True)

APPLIES_AI = "applies-ai"
"""스텁 키로 적용 질문을 가리키는 이름. 엔진이 적용 질문에 붙이는 조건 id 와 같다."""


# ── 문법 ────────────────────────────────────────────────────────────────────


class Expected(str, Enum):
    """픽스처가 기대하는 판정."""

    COMPLIANT = "compliant"
    NEEDS_REVIEW = "needs-review"
    NEEDS_REVIEW_UNCERTAIN = "needs-review-uncertain"
    NOT_APPLICABLE = "not-applicable"


class StubAnswer(str, Enum):
    """스텁 답. unknown 은 판정자가 '모름'이라고 **답한** 것이다(실패가 아니다). 판정에 '모름'으로 들어가 불확실로
    남는다. 판정자가 실패한 경우는 스텁을 적지 않은 것과 같다 — 판정에 넣지 않고 AI 확인 필요로 남긴다."""

    YES = "yes"
    NO = "no"
    NOT_APPLICABLE = "n/a"
    UNKNOWN = "unknown"


RAW = {StubAnswer.YES: "예", StubAnswer.NO: "아니오", StubAnswer.NOT_APPLICABLE: "해당없음", StubAnswer.UNKNOWN: "?"}


class Stub(_Base):
    """판정자가 이렇게 답했다고 치자. 근거 관문은 엔진이 그대로 적용한다."""

    answer: StubAnswer
    cite: str | None = None
    """코드 한 줄을 그대로 적는다. 줄 번호는 받지 않는다 — 판정자도 줄 번호가 아니라 글을 인용한다."""

    @model_validator(mode="before")
    @classmethod
    def _short_form(cls, v):
        # `ai-guard: no` 처럼 답만 적는 짧은 꼴
        return {"answer": v} if isinstance(v, str) else v

    @model_validator(mode="after")
    def _cite_only_for_yes(self) -> Stub:
        if self.cite is not None and self.answer is not StubAnswer.YES:
            raise ValueError("cite 는 answer: yes 에만 쓸 수 있습니다")
        return self


class FixtureCase(_Base):
    file: str
    """이 테스트 파일 기준 상대 경로."""
    id: str | None = None
    """기본값은 tests/ 기준 상대 경로. 같은 파일을 두 번 쓰면(스텁만 다르게) 반드시 적는다."""
    lang: str | None = None
    note: str | None = None
    """사람이 읽는 설명. 실패하면 함께 나온다."""
    expect: Expected | dict[str, Expected]
    """판정 하나(파일 맨 위 rule 에 대한 것)이거나 {'정책/규칙': 판정}."""
    ai: dict[str, Stub] = Field(default_factory=dict)
    """키는 기대한 규칙의 AI 조건 id, 또는 적용 질문이면 'applies-ai'."""
    decoy_for: list[str] = Field(default_factory=list)
    """이 픽스처가 흉내 내는 정적 대안 id('정책/규칙/대안' 꼴도 된다). 대안과 비슷한 모양이지만 그 대안으로
    풀리면 안 된다 — 그 규칙의 기대는 경고여야 한다. `--strict` 는 혼자 풀 수 있는 정적 대안마다 이런
    음성 픽스처를 하나 이상 요구한다. 대안이 경고를 풀 수 있는지만 보면, 조건 모양만 맞는 엉뚱한 코드를
    푸는 결함(야간에 보내는 블록, 비밀번호 길이 < 14)을 찾지 못한다."""


class PolicyTestFile(_Base):
    api_version: str = Field(alias="apiVersion")
    rule: str | None = None
    """'정책/규칙'. expect 가 판정 하나인 케이스가 있으면 반드시 적는다."""
    cases: list[FixtureCase] = Field(min_length=1)

    @field_validator("api_version")
    @classmethod
    def _api(cls, v: str) -> str:
        if v != TEST_API:
            raise ValueError(f"apiVersion 이 '{v}' 입니다. '{TEST_API}' 여야 합니다")
        return v

    @model_validator(mode="after")
    def _rule_for_short_expect(self) -> PolicyTestFile:
        for c in self.cases:
            if not isinstance(c.expect, dict) and self.rule is None:
                raise ValueError(f"{c.file}: expect 가 판정 하나면 파일 맨 위에 rule 을 적어야 합니다")
        return self


# ── 러너 ────────────────────────────────────────────────────────────────────

CLEAR = "clear"
"""기대를 적지 않은 규칙의 기대. 경고가 없으면(준수 또는 해당 없음) 통과다."""

FLAGGED_OUTCOMES = ("needs-review", "needs-review-uncertain")

#: 한 (픽스처, 규칙)에 판정이 여럿이면(scope: anchor) 가장 나쁜 것으로 본다.
SEVERITY = {
    "not-applicable": 0,
    "compliant": 1,
    "needs-review-uncertain": 2,
    "needs-review": 3,
}


@dataclass
class Fixture:
    id: str
    path: Path
    lang: str
    expects: dict[str, str]
    stubs: dict[tuple[str, str, str], tuple[str, str]] = field(default_factory=dict)
    note: str | None = None
    decoys: list[tuple[str, str]] = field(default_factory=list)
    """(정책/규칙, 대안 id). 이 픽스처는 그 대안을 흉내 내지만 풀리면 안 된다."""


def _read_yaml(p: Path) -> dict:
    try:
        raw = _yaml.load(p.read_text(encoding="utf-8"))
    except (YAMLError, UnicodeDecodeError, OSError) as e:
        raise PackError(f"{p}: 읽지 못했습니다\n{e}") from e
    if not isinstance(raw, dict):
        raise PackError(f"{p}: 최상위가 매핑이 아닙니다")
    return raw


def _ai_ids(rule) -> list[str]:
    return [q.id for q in rule.compliant_if_any if q.is_ai] + ([APPLIES_AI] if rule.applies_ai else [])


def load_test_file(p: Path, pack: PolicyPack, root: Path) -> list[Fixture]:
    try:
        tf = PolicyTestFile.model_validate(_read_yaml(p))
    except ValidationError as e:
        raise PackError(f"{p}: 테스트 파일이 문법에 맞지 않습니다\n{e}") from e
    rules = {f"{pol.id}/{r.id}": r for pol, r in pack.iter_rules()}
    out = []
    for c in tf.cases:
        path = p.parent / c.file
        if not path.is_file():
            raise PackError(f"{p}: 픽스처가 없습니다 — {c.file}")
        if engine_skips(path):
            # 엔진이 읽지 못하는 파일(.mts·대문자 확장자 등)은 구문 조건이 조용히 '거짓'이 된다.
            # 그런 픽스처의 기대가 맞아도 규칙에 대해 보여 주는 것이 없다
            raise PackError(f"{p}: {c.file}: 엔진이 읽지 못하는 확장자라 픽스처로 쓸 수 없습니다")
        if not_utf8(path):
            # 정규식 조건이 이 파일에서 아무것도 찾지 않는다. 같은 까닭이다
            raise PackError(f"{p}: {c.file}: UTF-8 이 아니라 픽스처로 쓸 수 없습니다")
        if isinstance(c.expect, dict):
            expects = {k: v.value for k, v in c.expect.items()}
        else:
            expects = {str(tf.rule): c.expect.value}
        for ref in expects:
            if ref not in rules:
                raise PackError(f"{p}: {c.file}: 팩에 없는 규칙 '{ref}'. 있는 것: {sorted(rules)}")
        stubs: dict[tuple[str, str, str], tuple[str, str]] = {}
        for key, stub in c.ai.items():
            if "/" in key:
                # '정책/규칙/조건' — 적용 질문(applies-ai)처럼 여러 규칙이 같은 이름을 쓸 때, 또는 기대를
                # 적지 않은 규칙의 질문에 답할 때 쓴다
                ref, pred = key.rsplit("/", 1)
                if ref not in rules or pred not in _ai_ids(rules[ref]):
                    raise PackError(f"{p}: {c.file}: ai 의 '{key}' 는 팩에 있는 규칙의 AI 조건이 아닙니다")
                policy, rule = ref.split("/", 1)
                stubs[(policy, rule, pred)] = (RAW[stub.answer], stub.cite or "")
                continue
            owners = [ref for ref in expects if key in _ai_ids(rules[ref])]
            if not owners:
                raise PackError(f"{p}: {c.file}: ai 의 '{key}' 는 기대한 규칙의 AI 조건이 아닙니다")
            if len(owners) > 1:
                raise PackError(
                    f"{p}: {c.file}: ai 의 '{key}' 가 여러 규칙({owners})에 있습니다. '정책/규칙/{key}' 꼴로 적으세요"
                )
            policy, rule = owners[0].split("/", 1)
            stubs[(policy, rule, key)] = (RAW[stub.answer], stub.cite or "")
        decoys = [_decoy(p, c.file, d, expects, rules) for d in c.decoy_for]
        out.append(
            Fixture(
                id=c.id or path.relative_to(root).as_posix(),
                path=path,
                lang=c.lang or language_of(path),
                expects=expects,
                stubs=stubs,
                note=c.note,
                decoys=decoys,
            )
        )
    return out


def _decoy(p: Path, file: str, name: str, expects: dict[str, str], rules: dict) -> tuple[str, str]:
    """decoy-for 한 항목 → (정책/규칙, 대안 id). 기대한 규칙의 정적 대안이어야 하고, 그 규칙의 기대는 경고다."""
    if "/" in name:
        ref, pred = name.rsplit("/", 1)
        owners = [ref] if ref in expects else []
    else:
        ref, pred = "", name
        owners = [r for r in expects if any(q.id == name for q in rules[r].compliant_if_any)]
    if len(owners) != 1:
        raise PackError(
            f"{p}: {file}: decoy-for 의 '{name}' 는 기대한 규칙 하나의 대안이어야 합니다"
            + (f" (여러 규칙에 있습니다: {owners}. '정책/규칙/{name}' 꼴로 적으세요)" if owners else "")
        )
    ref = owners[0]
    alt = next((q for q in rules[ref].compliant_if_any if q.id == pred), None)
    if alt is None or alt.is_ai:
        raise PackError(f"{p}: {file}: decoy-for 의 '{name}' 는 {ref} 의 정적 대안이 아닙니다")
    if expects[ref] not in FLAGGED_OUTCOMES:
        raise PackError(f"{p}: {file}: decoy-for 로 적은 {ref} 의 기대가 경고가 아닙니다({expects[ref]})")
    return ref, pred


def collect(paths: list[Path], pack: PolicyPack) -> list[Fixture]:
    """경로마다 픽스처를 모은다. 폴더면 그 아래 *.test.yaml 전부다. 팩 폴더를 그 팩의 tests/ 로 바꾸는 것은 부르는
    쪽(cmd_test)이 한다. 여기서 pack.yaml 이 있는지로 짐작하면 이름이 다른 팩 파일일 때 틀린다."""
    out: list[Fixture] = []
    for given in paths:
        if given.is_dir():
            stray = sorted(str(q) for q in given.rglob("*.test.yml"))
            if stray:
                raise ConfigError(f"읽지 않는 확장자입니다: {', '.join(stray)} — .test.yaml 로 바꾸세요")
            for f in sorted(given.rglob("*.test.yaml")):
                out.extend(load_test_file(f, pack, given))
        elif given.name.endswith(".test.yaml"):
            out.extend(load_test_file(given, pack, given.parent))
        elif given.name.endswith(".test.yml"):
            raise ConfigError(f"읽지 않는 확장자입니다: {given} — .test.yaml 로 바꾸세요")
        else:
            raise ConfigError(f"테스트 파일(*.test.yaml)도 디렉터리도 아닙니다: {given}")
    ids = [f.id for f in out]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise PackError(f"픽스처 id 가 겹칩니다: {dupes}. 같은 파일을 두 번 쓰려면 id 를 적으세요")
    return out


class StubJudge:
    """픽스처에 적힌 답을 준다. 적힌 게 없으면 실패(failure="missing")를 주고 missing 에 쌓는다.

    근거 관문은 여기서가 아니라 엔진이 적용한다. 답이 없는 질문은 판정자가 실패한 답과 같이 판정에 넣지
    않는다(판정자가 없을 때와 같은 결론). 답을 적지 않은 질문은 판정이 기대와 맞아도 시험이 실패한다.
    """

    id = "stub"

    def __init__(self, fixtures: list[Fixture]) -> None:
        self.table = {(fx.id, *k): v for fx in fixtures for k, v in fx.stubs.items()}
        self.used: set[tuple] = set()
        self.asked: list[Question] = []
        self.missing: list[Question] = []

    def ask(self, q: Question) -> Answer:
        key = (q.case, q.policy, q.rule, q.predicate)
        self.asked.append(q)
        hit = self.table.get(key)
        if hit is None:
            self.missing.append(q)
            return Answer(raw="?", failure="missing")
        self.used.add(key)
        raw, cite = hit
        return Answer(raw=raw, evidence=cite)  # type: ignore[arg-type]


@dataclass
class Row:
    fixture: Fixture
    ref: str
    expected: str
    actual: str
    unanswered: list[str]
    trace: list[str]

    @property
    def declared(self) -> bool:
        return self.ref in self.fixture.expects

    @property
    def passed(self) -> bool:
        return matches(self.expected, self.actual) and not self.unanswered


def matches(expected: str, actual: str) -> bool:
    if expected == CLEAR:
        return actual in ("compliant", "not-applicable")
    return expected == actual


@dataclass
class Coverage:
    rule: str
    raising: list[str]
    sole: dict[str, list[str]]
    """대안 id → 그 대안이 없었다면 경고가 났을 픽스처(= 그 대안 하나로 풀린 픽스처)."""
    never_true: list[str]
    not_testable: list[str]
    """혼자서는 경고를 풀 수 없는 대안(약한 정적 대안은 AI 확인이 있어야 푼다). 빈틈으로 세지 않는다."""
    gaps: list[str]
    decoys: dict[str, list[str]] = field(default_factory=dict)
    """혼자 풀 수 있는 정적 대안 id → 그 대안을 흉내 낸 음성 픽스처(decoy-for)."""


@dataclass
class TestRun:
    rows: list[Row]
    coverage: list[Coverage]
    fixtures: list[Fixture]
    stats: dict[str, int]
    """questions_asked(판정자에게 넘긴 질문 수) · missing(스텁이 없던 질문 수)."""
    unused_stubs: list[tuple]
    static_seconds: float
    engine: str = ""
    """정적 조건을 돌린 엔진과 판본."""
    engine_runs: int = 1
    """엔진을 부른 횟수. 픽스처가 많으면 나눠 부른다."""
    engine_errors: list[str] = field(default_factory=list)
    """엔진이 어느 파일인지 밝히지 않은 오류. 있으면 그 실행의 픽스처는 전부 '모름' 쪽으로 기운다 —
    대량 실패의 원인이 규칙이 아니라 엔진이라는 것을 알려야 한다."""

    @property
    def failed(self) -> list[Row]:
        return [r for r in self.rows if not r.passed]

    @property
    def gaps(self) -> int:
        return sum(len(c.gaps) for c in self.coverage)


def outcome_table(pack: PolicyPack, fixtures: list[Fixture], result: EvalResult) -> dict[tuple[str, str], str]:
    """(픽스처, 규칙) → 판정. 경고가 없으면 준수(판정 단위가 있었음) 또는 해당 없음."""
    out: dict[tuple[str, str], str] = {}
    for f in result.findings:
        key = (f.case, f.ref)
        if key not in out or SEVERITY[f.outcome.value] > SEVERITY[out[key]]:
            out[key] = f.outcome.value
    units = {(u.target.case, u.ref) for u in result.units}
    for fx in fixtures:
        for pol, r in pack.iter_rules():
            key = (fx.id, f"{pol.id}/{r.id}")
            out.setdefault(key, "compliant" if key in units else "not-applicable")
    return out


def run(pack: PolicyPack, fixtures: list[Fixture], backend, coverage_scope: set[str] | None = None) -> TestRun:
    """모든 픽스처를 합쳐 semgrep 을 한 번 돌리고 evaluate 를 한 번 부른다. 판정자는 늘 스텁이다."""
    t0 = time.time()
    static = backend.run(compile_static(pack), sorted({f.path for f in fixtures}))
    static_s = time.time() - t0
    static.check_rules()

    judge = StubJudge(fixtures)
    targets = [Target(path=f.path, lang=f.lang, case=f.id) for f in fixtures]
    res = evaluate(pack, targets, static, judge=judge)
    missing: dict[str, list[str]] = {}
    for q in judge.missing:
        missing.setdefault(q.case, []).append(f"{q.policy}/{q.rule}/{q.predicate}")
    asked = {(u.policy.id, u.rule.id, p.id) for u in res.units for p, _, _ in u.ai_alts}
    asked |= {(q.policy, q.rule, q.predicate) for q in judge.asked}

    table = outcome_table(pack, fixtures, res)
    traces: dict[tuple[str, str], list[str]] = {}
    for u in res.units:
        traces.setdefault((u.target.case, u.ref), []).extend(u.trace)
    rows: list[Row] = []
    for fx in fixtures:
        for pol, r in pack.iter_rules():
            ref = f"{pol.id}/{r.id}"
            rows.append(
                Row(
                    fixture=fx,
                    ref=ref,
                    expected=fx.expects.get(ref, CLEAR),
                    actual=table[(fx.id, ref)],
                    unanswered=[m for m in missing.get(fx.id, []) if m.startswith(ref + "/")],
                    trace=traces.get((fx.id, ref), []),
                )
            )

    return TestRun(
        rows=rows,
        coverage=coverage(pack, static, fixtures, res, asked, scope=coverage_scope),
        fixtures=fixtures,
        stats={"questions_asked": res.questions_asked, "missing": len(judge.missing)},
        unused_stubs=sorted(set(judge.table) - judge.used),
        static_seconds=static_s,
        engine=static.engine,
        engine_runs=static.runs or 1,
        engine_errors=list(static.unlocated_errors),
    )


# ── 대안별 커버리지 ─────────────────────────────────────────────────────────


def _compliant(alts: list[tuple], ai_values: list, answered: bool):
    considered = considered_values(alts, ai_values, answered)
    return or3(considered) if considered else FALSE


def can_clear_alone(rule, pred: Predicate) -> bool:
    """이 대안 하나만 참이면 규칙이 풀리는가.

    규칙을 다시 적지 않고 planner 의 함수에 합성한 값을 넣어 계산한다. 두 곳에 같은 규칙을
    적으면 언젠가 어긋난다.
    """
    alts = [
        ("ai" if q.is_ai else "static", q, None if q.is_ai else (TRUE if q is pred else FALSE))
        for q in rule.compliant_if_any
    ]
    static_alts = [a for a in alts if a[0] == "static"]
    # 엔진처럼: 물을 AI 대안이 있어야 물은 것이다
    asked = needs_alternative_questions(static_alts) and any(q.is_ai for q in rule.compliant_if_any)
    ai_values = [TRUE if q is pred else FALSE for q in rule.compliant_if_any if q.is_ai] if asked else []
    return _compliant(alts, ai_values, asked) is TRUE


def _necessary(u: Unit, pred: Predicate) -> bool:
    """이 대안을 거짓으로 바꾸면 준수가 깨지는가. 곧 이 대안 하나로 풀렸는가."""
    alts = [(k, p, FALSE if (p is pred and k == "static") else v) for k, p, v in u.alts]
    ai_values = [FALSE if p is pred else v for p, _, v in u.ai_alts]
    return _compliant(alts, ai_values, u.answered) is not TRUE


def coverage(
    pack: PolicyPack,
    static,
    fixtures: list[Fixture],
    res: EvalResult,
    asked: set[tuple],
    scope: set[str] | None = None,
) -> list[Coverage]:
    """규칙마다 위반 픽스처·대안별 단독 해제·음성 픽스처가 있는지 센다.

    scope 가 있으면 그 규칙만 센다(테스트 파일 몇 개만 돌렸을 때). 팩 전체를 돌리면 모든 규칙을
    센다 — 테스트 파일이 아예 없는 새 정책도 빈틈으로 드러나야 한다."""
    out: list[Coverage] = []
    # 함수 단위 규칙은 한 픽스처에서 판정이 여럿 난다. 기대 판정과 같게 가장 나쁜 판정을 본다
    flagged: dict[tuple, str] = {}
    for f in res.findings:
        key = (f.case, f.ref)
        if SEVERITY.get(f.outcome.value, 0) > SEVERITY.get(flagged.get(key, ""), -1):
            flagged[key] = f.outcome.value
    for pol, r in pack.iter_rules():
        ref = f"{pol.id}/{r.id}"
        if scope is not None and ref not in scope:
            continue
        raising: list[str] = []
        sole: dict[str, list[str]] = {p.id: [] for p in r.compliant_if_any}
        decoys: dict[str, list[str]] = {}
        seen_true: set[str] = set()
        asked_any = {p for (pp, rr, p) in asked if pp == pol.id and rr == r.id}
        for fx in fixtures:
            for dref, dpred in fx.decoys:
                if dref == ref:
                    decoys.setdefault(dpred, []).append(fx.id)
            target = Target(path=fx.path, lang=fx.lang, case=fx.id)
            for p in r.applies_when:
                key = PredicateKey(pol.id, r.id, GROUP_APPLIES, p.id)
                if static_value(p, key, target, static) is TRUE:
                    seen_true.add(p.id)
        for u in res.units:
            if u.ref != ref:
                continue
            seen_true |= {p.id for k, p, v in u.alts if k == "static" and v is TRUE}
            seen_true |= {p.id for p, _, v in u.ai_alts if v is TRUE}
            outcome = flagged.get((u.target.case, ref))
            if outcome == "needs-review" and u.target.case not in raising:
                raising.append(u.target.case)
            if outcome is not None:
                continue
            for p in r.compliant_if_any:
                if _necessary(u, p) and u.target.case not in sole[p.id]:
                    sole[p.id].append(u.target.case)

        gaps: list[str] = []
        if not raising:
            gaps.append("위반 모양을 보여 주는 픽스처(검토 필요)가 없습니다")
        not_testable = [p.id for p in r.compliant_if_any if not can_clear_alone(r, p)]
        for p in r.compliant_if_any:
            if p.id not in not_testable and not sole[p.id]:
                gaps.append(f"대안 {p.id} 하나만으로 풀리는 픽스처가 없습니다")
        # 혼자 풀 수 있는 정적 대안은 '비슷하지만 풀리면 안 되는' 음성 픽스처도 있어야 한다.
        # 음성 비율(음성 a/b)도 이 대안들로만 센다. 혼자 풀 수 없는 대안에 단 decoy-for 는
        # 기대로는 시험되지만 빈틈을 메우는 것은 아니다
        clearers = [p for p in r.compliant_if_any if not p.is_ai and p.id not in not_testable]
        decoys = {p.id: decoys.get(p.id, []) for p in clearers}
        for p in clearers:
            if not decoys[p.id]:
                gaps.append(f"대안 {p.id} 를 흉내 내지만 풀리면 안 되는 음성 픽스처(decoy-for)가 없습니다")
        never_true = [
            p.id
            for p in list(r.applies_when) + list(r.compliant_if_any)
            if (p.id not in asked_any if p.is_ai else p.id not in seen_true)
        ]
        gaps += [f"조건 {k} 가 어느 픽스처에서도 참이 된 적(AI 면 물은 적)이 없습니다" for k in never_true]
        out.append(Coverage(ref, raising, sole, never_true, not_testable, gaps, decoys))
    return out
