"""정책 팩 문법 v0.3 — 단일 진실 원천.

JSON Schema 는 이 모델에서 생성하고(`policypack schema --write`), 로더도 검증기도
이 모델만 본다. 문법을 바꾸려면 여기만 고친다.

## 원칙

1. **해석기가 읽는 키만 둔다.** 적어 두었는데 동작하지 않는 키는 사용자를 속인다.

2. **모르는 키는 오류다.** (`extra="forbid"`) 오타 난 조건이 조용히 빠지면
   규칙이 꺼진 줄 모르고 쓰게 된다.

3. **방향성 신뢰를 문법에 넣는다.** 대안의 `strength` 와 AI 조건의 `evidence` 가
   "이 근거가 경고를 내릴 자격이 있는가"를 표현한다.
"""

from __future__ import annotations

import datetime as _dt
from enum import Enum
from pathlib import PurePosixPath as _PurePosixPath
from pathlib import PureWindowsPath as _PureWindowsPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

API_VERSION = "policypack/v0.3"


def _kebab(name: str) -> str:
    return name.replace("_", "-")


class _Base(BaseModel):
    # 팩 파일의 키는 케밥(compliant-if-any)만 받는다. 파이썬 이름(compliant_if_any)도 받으면 CLI 는 통과하고
    # 편집기(스키마)는 거절해 둘이 어긋났다(끝까지 점검에서 실측)
    model_config = ConfigDict(
        alias_generator=_kebab,
        validate_by_name=False,
        validate_by_alias=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


# ── 열거형 ──────────────────────────────────────────────────────────────────


class Strength(str, Enum):
    """대안 근거의 강도.

    strong 대안은 참이면 혼자 경고를 푼다.
    weak 는 이름·문자열만 보는 대안이다. 참이어도 혼자 경고를 풀지 못하고 같은 규칙의 AI 대안에게
    다시 묻는다. 판정자가 없거나 답하지 못하면 '모름'이 되어 불확실로 남는다.
    """

    STRONG = "strong"
    WEAK = "weak"


class Evidence(str, Enum):
    """AI 대안의 '예'를 인정하는 조건. 어느 쪽이든 코드에 실제로 있는 줄을 인용해야 한다.

    관문이 받지 않은 '예'는 '거짓'이 되지 않고 판정에서 빠져(판정자가 없을 때처럼) 경고가 남는다 — 인용 관문의 비대칭.
    required  주석만 인용한 '예'는 받지 않는다. 코드 줄 끝에 붙은 주석은 떼고 본다
    strict    인용을 한 글자도 고치지 않고 주석을 뗀 코드에서 찾는다. 끝에 주석이 붙은 줄을 통째로
              인용해도 받지 않는다. '이 문구가 코드에 실제로 있는가'를 묻는 대안에 쓴다
    """

    REQUIRED = "required"
    STRICT = "strict"


class Scope(str, Enum):
    """판정 단위.

    file    (정책, 규칙, 파일)마다 판정 하나. 기본값이다
    anchor  anchor-on 조건이 맞은 자리를 감싸는 가장 바깥 함수마다 판정 하나.
            대안은 그 함수와 겹치는 매치만, AI 의 '예'는 그 함수 안의 줄 인용만 인정한다.
            그래서 anchor 가 경고한 집합은 file 이 경고한 집합을 늘 포함한다(경고를 올리기만 한다)
    """

    FILE = "file"
    ANCHOR = "anchor"


# ── 조건 ────────────────────────────────────────────────────────────────────

#: 정적 조건에 쓸 수 있는 Semgrep 키. 이 밖의 키는 오류다.
SEMGREP_KEYS = frozenset(
    {
        "pattern",
        "patterns",
        "pattern-either",
        "pattern-regex",
        "pattern-not",
        "pattern-not-regex",
        "pattern-inside",
        "pattern-not-inside",
        "metavariable-regex",
        "metavariable-pattern",
        "metavariable-comparison",
        "focus-metavariable",
        "mode",
        "pattern-sources",
        "pattern-sinks",
        "pattern-sanitizers",
        "pattern-propagators",
    }
)

#: 파일이 파싱되지 않아도 값을 낼 수 있는 키. generic 사본으로 따로 컴파일한다.
#: (실측: 파일 전체가 Syntax error 면 languages 가 붙은 정규식 규칙도 매치되지 않는다)
PARSE_INDEPENDENT_KEYS = frozenset({"pattern-regex", "pattern-not-regex"})


def _check_static(owner: str, static: dict[str, Any]) -> None:
    if not static:
        raise ValueError(f"조건 '{owner}': static 이 비어 있습니다")
    unknown = set(static) - SEMGREP_KEYS
    if unknown:
        raise ValueError(
            f"조건 '{owner}': 알 수 없는 Semgrep 키 {sorted(unknown)}. 쓸 수 있는 키: {sorted(SEMGREP_KEYS)}"
        )


class OnUnsatisfied(_Base):
    """이 대안이 참이 아닐 때 사람에게 할 말.

    대안마다 따로 둔다. Kyverno 의 anyPattern 은 "여러 형태 중 하나"는 표현하지만
    어느 것이 왜 안 맞았는지는 말해 주지 못한다.
    """

    message: str
    ask_developer: str | None = None
    remediation: str | None = None


class AiCondition(_Base):
    question: str
    evidence: Evidence = Evidence.REQUIRED


class Condition(_Base):
    """적용 조건 하나(applies-when 의 항목). Semgrep 조건만 받는다.

    적용 여부를 AI 에게 물으려면 규칙의 applies-ai 에 적는다. 여기 AI 조건을 두면 묻지 않고
    거짓이 되어 규칙이 꺼지므로 문법이 막는다.
    """

    id: str
    static: dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def _no_ai(cls, v: Any) -> Any:
        if isinstance(v, dict) and "ai" in v:
            raise ValueError(
                f"조건 '{v.get('id')}': applies-when 은 정적 조건만 받습니다. "
                f"AI 적용 질문은 applies-ai 에 적으세요(여기 두면 묻지 않고 거짓이 되어 규칙이 꺼집니다)"
            )
        return v

    @model_validator(mode="after")
    def _check(self) -> Condition:
        _check_static(self.id, self.static)
        return self

    @property
    def is_ai(self) -> bool:
        return False

    @property
    def parse_independent(self) -> bool:
        """정규식 키만으로 이루어진 조건은 파싱 실패와 무관하게 참·거짓을 낸다(generic 사본)."""
        return set(self.static) <= PARSE_INDEPENDENT_KEYS


class Predicate(_Base):
    """적법한 대안 하나(compliant-if-any 의 항목). static 과 ai 중 정확히 하나를 적는다."""

    # 아래 검사기의 규칙을 스키마에도 적는다. 편집기가 CLI 와 같은 것을 거절하게 한다
    model_config = ConfigDict(json_schema_extra={"oneOf": [{"required": ["static"]}, {"required": ["ai"]}]})

    id: str
    strength: Strength = Strength.STRONG
    static: dict[str, Any] | None = None
    ai: AiCondition | None = None
    on_unsatisfied: OnUnsatisfied | None = None

    @model_validator(mode="after")
    def _exactly_one_body(self) -> Predicate:
        if (self.static is None) == (self.ai is None):
            raise ValueError(f"조건 '{self.id}': static 과 ai 중 정확히 하나가 있어야 합니다")
        if self.static is not None:
            _check_static(self.id, self.static)
        return self

    @property
    def is_ai(self) -> bool:
        return self.ai is not None

    @property
    def parse_independent(self) -> bool:
        """정규식 키만으로 이루어진 조건은 파싱 실패와 무관하게 참·거짓을 낸다(generic 사본)."""
        return self.static is not None and set(self.static) <= PARSE_INDEPENDENT_KEYS


# ── 규칙과 정책 ─────────────────────────────────────────────────────────────


class AppliesAi(_Base):
    """적용 판단을 AI에게 묻는 질문.

    정적 적용 판단이 '모름'일 때만 부른다. 적용의 '예'는 경고를 올리는 쪽이라 인용을 요구하지 않는다.
    적용 질문의 '아니오'는 인용 없이 규칙을 끄므로, 정적 조건이 이미 참인 곳에서는 묻지 않는다.
    """

    question: str


class Rule(_Base):
    # 대안이 없는 규칙은 아래 검사기가 거절한다. 스키마에서도 빠진 키를 알리게 required 에 넣는다
    model_config = ConfigDict(json_schema_extra=lambda s: s.setdefault("required", []).append("compliant-if-any"))

    id: str
    languages: list[str] | None = None
    scope: Scope = Scope.FILE
    anchor_on: str | None = None
    """scope: anchor 에서 판정 위치를 낼 applies-when 조건 id."""
    applies_when: list[Condition] = Field(default_factory=list)
    applies_ai: AppliesAi | None = None
    compliant_if_any: list[Predicate] = Field(default_factory=list, json_schema_extra={"minItems": 1})

    @model_validator(mode="after")
    def _check(self) -> Rule:
        if not self.compliant_if_any:
            raise ValueError(
                f"규칙 '{self.id}': compliant-if-any 가 비어 있습니다. 적법한 대안을 하나 이상 적어야 합니다"
            )
        if not self.applies_when and self.applies_ai is None:
            raise ValueError(f"규칙 '{self.id}': applies-when 과 applies-ai 가 모두 없습니다. 모든 파일에 적용됩니다")
        _unique(
            [p.id for p in self.applies_when],
            f"규칙 '{self.id}' 의 applies-when 안에서 조건 id",
        )
        _unique(
            [p.id for p in self.compliant_if_any],
            f"규칙 '{self.id}' 의 compliant-if-any 안에서 조건 id",
        )
        # 정적 조건은 '정책.규칙.조건' 으로 Semgrep 규칙 id 가 되고 묶음(applies-when·compliant-if-any)은
        # 들어가지 않는다. 두 묶음에 같은 id 가 있으면 Semgrep 규칙 id 가 겹치므로 팩을 읽을 때 막는다
        both = {p.id for p in self.applies_when} & {p.id for p in self.compliant_if_any}
        if both:
            raise ValueError(
                f"규칙 '{self.id}': 적용 조건과 대안의 id 가 같습니다: {sorted(both)}. "
                f"조건 id 는 규칙 안에서 하나여야 합니다"
            )
        if self.anchor_on is not None:
            if self.scope is not Scope.ANCHOR:
                raise ValueError(f"규칙 '{self.id}': anchor-on 은 scope: anchor 에서만 씁니다(file 에서는 안 읽힌다)")
            if self.anchor_on not in {p.id for p in self.applies_when}:
                raise ValueError(
                    f"규칙 '{self.id}': anchor-on '{self.anchor_on}' 이 applies-when 에 없습니다. "
                    f"있는 조건: {[p.id for p in self.applies_when] or '(없음)'}"
                )
        elif self.scope is Scope.ANCHOR:
            raise ValueError(
                f"규칙 '{self.id}': scope: anchor 에는 anchor-on 이 필요합니다. "
                f"어느 applies-when 조건이 맞은 자리를 판정 위치로 쓸지 적으세요"
            )
        if all(p.is_ai for p in self.compliant_if_any):
            raise ValueError(
                f"규칙 '{self.id}': 대안이 전부 AI 조건입니다. "
                f"정적 대안이 하나도 없으면 지연 평가가 의미를 잃고 매번 AI를 부르게 됩니다"
            )
        return self


class LegalRef(_Base):
    """근거 조문.

    해시 대상은 원격 페이지가 아니라 저장소에 커밋한 원문 파일(`text-file`)이다.
    법제처 페이지 구조가 바뀌어도 검증이 깨지지 않게 하기 위해서다.
    """

    statute: str
    article: str
    clause: str | None = None
    law_id: str | None = None
    url: str | None = None
    text_file: str | None = None
    text_sha256: str | None = None
    text_retrieved: _dt.date | None = None
    effective_from: _dt.date | None = None

    @model_validator(mode="after")
    def _check(self) -> LegalRef:
        if self.text_sha256 and not self.text_file:
            raise ValueError(f"{self.statute} {self.article}: text-sha256 이 있는데 text-file 이 없습니다")
        if self.text_file:
            # 팩 밖의 파일을 가리키면 SARIF 가 그 내용을 조문으로 싣는다(끝까지 점검에서 실측: ../ 로 팩 밖의 파일)
            posix, win = _PurePosixPath(self.text_file.replace("\\", "/")), _PureWindowsPath(self.text_file)
            if posix.is_absolute() or win.is_absolute() or win.drive or ".." in posix.parts:
                raise ValueError(
                    f"{self.statute} {self.article}: text-file 은 팩 폴더 안의 상대 경로여야 합니다 — {self.text_file}"
                )
        return self


class Legal(_Base):
    violated_when_failed: list[LegalRef] = Field(min_length=1)


class Review(_Base):
    """재검토 기한. 지나면 validate 가 경고한다.

    법은 개정된다. 규칙이 언제 마지막으로 확인됐는지 모르면 조용히 낡는다.
    """

    review_by: _dt.date


class Rationale(_Base):
    motivation: str | None = None
    implementation: str | None = None


class Policy(_Base):
    id: str
    category: str
    title: str
    ask_developer: str | None = None
    legal: Legal | None = None
    review: Review | None = None
    rationale: Rationale | None = None
    rules: list[Rule] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> Policy:
        _unique([r.id for r in self.rules], f"정책 '{self.id}' 안에서 규칙 id")
        return self


# ── 팩 수준 ─────────────────────────────────────────────────────────────────


class Defaults(_Base):
    languages: list[str] = Field(default_factory=lambda: ["javascript", "typescript"])


class PackMeta(_Base):
    id: str
    title: str


class PolicyPack(_Base):
    api_version: str = Field(alias="apiVersion", json_schema_extra={"const": API_VERSION})
    pack: PackMeta
    defaults: Defaults = Field(default_factory=Defaults)
    policies: list[Policy] = Field(min_length=1)

    @field_validator("api_version")
    @classmethod
    def _api(cls, v: str) -> str:
        if v != API_VERSION:
            raise ValueError(f"apiVersion 이 '{v}' 입니다. 이 해석기는 '{API_VERSION}' 만 읽습니다")
        return v

    @model_validator(mode="after")
    def _check(self) -> PolicyPack:
        _unique([p.id for p in self.policies], "정책 id")
        for pol in self.policies:
            # 판정은 '정책/규칙' 으로 가리킨다. '/' 가 들어가면 a/b + c 와 a + b/c 가 같아진다
            for bad in [pol.id, *(r.id for r in pol.rules)]:
                if "/" in bad:
                    raise ValueError(f"정책 '{pol.id}': id 에 '/' 를 쓸 수 없습니다: '{bad}'")
        return self

    def languages_for(self, rule: Rule) -> list[str]:
        return rule.languages or self.defaults.languages

    def iter_rules(self):
        """(정책, 규칙) 쌍을 순서대로 낸다."""
        for pol in self.policies:
            for rule in pol.rules:
                yield pol, rule


def _unique(ids: list[str], what: str) -> None:
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            raise ValueError(f"{what} 가 중복됩니다: '{i}'")
        seen.add(i)
