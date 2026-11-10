"""판정자 인터페이스.

판정자는 **모델이 뭐라고 했는지만** 돌려준다(Answer 에는 세 값도 관문 결과도 없다). 근거 관문은
엔진이 적용한다(engine._answer_to_tri). 그래서 실제 모델·정책 테스트의 스텁·시험용 가짜 판정자가
모두 같은 관문을 거친다.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal, Protocol

SYSTEM = "너는 코드 보안·개인정보 검토자다. 요청한 JSON 형식으로만 답한다."

CLOSED_PROMPT = """아래 코드가 다음 조건에 해당하는지 판정하라.

조건: {question}

JSON만 출력한다: {{"answer": "예" 또는 "아니오", "evidence": "<판단 근거가 된 코드 한 줄을 그대로 인용. 해당 없으면 빈 문자열>"}}

코드({lang}):
{fence}
{code}
{fence}"""

FRAGMENT_NOTE = {
    "function": """

위 코드는 파일 전체가 아니라 함수 하나다. 값이 어디서 오는지(매개변수, this 필드, 본문이 보이지 않는 함수)가 위 코드와 아래 참고 줄에 보이지 않으면 외부 입력일 수 있다고 보라. 조건을 만족한다는 근거가 위 코드에 직접 보일 때만 "예"라고 답하라.""",
    "top-level": """

위 코드는 파일 전체가 아니라 함수 밖(모듈 최상위)의 줄이다. 함수 본문은 비웠다. 조건을 만족한다는 근거가 위 코드에 직접 보일 때만 "예"라고 답하라.""",
}

HEADER_BLOCK = """

참고 — 같은 파일에서 위 코드가 쓰는 최상위 선언과 import, 위 함수를 부르는 줄, 위 코드가 읽는 this 필드에 값을 넣는 줄이다. `// …` 는 그 사이를 뺐다는 표시다. **판정 대상이 아니다.** 위 "코드"에 대해 판정하고, 근거도 위 "코드"에서 인용하라.
{fence}
{header}
{fence}"""

RawAnswer = Literal["예", "아니오", "해당없음", "?"]
Failure = Literal["timeout", "isolation", "parse", "transport", "missing"]
"""판정자가 쓸 만한 답을 주지 못한 이유. `missing` 은 정책 테스트의 스텁에 그 질문의 답이 없다는 뜻이다(모델을 부르지 않음)."""


@dataclass(frozen=True)
class Question:
    """판정자에게 보낼 질문 하나.

    `policy`·`rule`·`predicate`·`case` 는 프롬프트에 들어가지 않는다. 정책 테스트의 스텁 판정자가 답을
    찾는 열쇠다(`case` 는 픽스처 id 이고, 실제 저장소를 스캔할 때는 None 이다).
    """

    text: str
    code: str
    lang: str
    policy: str = ""
    rule: str = ""
    predicate: str = ""
    case: str | None = None
    header: str = ""
    """함수 단위(scope: anchor) 판정에서 `code` 는 그 함수뿐이다. 함수만 보면 `path` 가 어느 모듈인지,
    쓰인 헬퍼가 무엇을 하는지, 값이 어디서 오는지 모르므로 같은 파일의 참고 줄을 붙인다
    (engine.file_header). 파일 단위 판정에서는 비어 있다."""
    fragment: str = ""
    """`code` 가 파일의 일부면 그 종류("function" | "top-level"). 파일 전체면 빈 문자열."""

    def prompt(self) -> str:
        fence = _fence(self.code + self.header)
        base = CLOSED_PROMPT.format(question=self.text, lang=self.lang, code=self.code.strip(), fence=fence)
        if self.fragment:
            base += FRAGMENT_NOTE[self.fragment]
        if self.header.strip():
            base += HEADER_BLOCK.format(header=self.header.strip(), fence=fence)
        return base


def _fence(text: str) -> str:
    """코드를 감쌀 울타리. 코드 속 가장 긴 백틱 줄보다 길게 한다. 코드의 ``` 가 블록을 닫으면 그 뒤의 글이 코드가
    아니라 지시로 읽힌다(끝까지 점검에서 실측: AI 채팅 화면의 마크다운 문자열)."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


@dataclass(frozen=True)
class Answer:
    """모델이 뭐라고 했는지. 세 값도 관문 결과도 여기 없다."""

    raw: RawAnswer = "?"
    evidence: str = ""
    failure: Failure | None = None
    unreachable: bool = False
    """서비스에 닿지 못했다(전송이 재시도를 다 썼거나 키·모델이 틀렸다). 그 질문만의 문제가 아니다."""


class Judge(Protocol):
    id: str

    def ask(self, q: Question) -> Answer: ...


class OncePerRun:
    """같은 프롬프트를 한 실행에서 두 번 보내지 않는다. 실제 판정자(build)를 늘 이것으로 감싼다.

    엔진은 (정책, 규칙, 대상[, 구역])마다 한 번만 묻는다. 그래도 규칙이 달라 같은 질문·같은 코드가 다시
    나온다(kr.network-act.50-4 의 다섯 규칙 가운데 문자 규칙 둘, 이메일 규칙 셋이 각각 같은 적용 질문을 쓴다). 실패한 답도 다시 묻지 않는다 — 한 실행
    안에서 같은 질문의 답이 갈리면 판정이 흔들린다. 실행이 끝나면 버린다(저장하지 않는다).

    판정자가 연달아 GIVE_UP_AFTER 번 시간 안에 답하지 않거나 서비스에 닿지 못하면(`Answer.unreachable`) 이 실행에서는
    더 부르지 않는다. 멈춘 판정자는 질문마다
    시간 제한을 다 쓰고(claude-cli 180초) 질문은 하나씩 간다. 질문이 수백 개면 몇 시간이다(실측: 245개 ≈ 12시간).
    그 질문만 거절된 것은 세지 않는다. 너무 긴 프롬프트처럼 그 질문만의 문제일 수 있다(검토에서 실측: 큰 파일 셋이 이어지자
    나머지 질문을 버렸다). 묻지 않은 질문은 부르지 못한 것(transport)으로 답해 'AI 확인 필요'로 남고 `skipped` 에 센다.

    정책 테스트의 스텁 판정자는 감싸지 않는다. 스텁은 (픽스처, 정책, 규칙, 조건)마다 답이 따로다.

    실제 판정자로 가는 길은 이것 하나라 비밀값도 여기서 가린다(egress.mask, 줄 수는 그대로). 가린 줄을 인용한 답은
    코드에 없는 인용이라 관문을 넘지 못하고 '불확실'로 남는다. 가린 수는 `masked` 에 모아 보고서 run.judge_masked 에
    싣는다.
    """

    GIVE_UP_AFTER = 3

    def __init__(self, inner: Judge) -> None:
        self.inner = inner
        self.id = inner.id
        self._answers: dict[str, Answer] = {}
        self._timeouts = 0
        self.skipped = 0
        self.sent = 0
        self.masked: dict[str, int] = {}

    def ask(self, q: Question) -> Answer:
        key = hashlib.sha256(q.prompt().encode("utf-8")).hexdigest()
        if key in self._answers:
            return self._answers[key]
        if self._timeouts >= self.GIVE_UP_AFTER:
            self.skipped += 1
            a = Answer(raw="?", failure="transport")
        else:
            a = self.inner.ask(self._mask(q))
            self.sent += 1
            self._timeouts = self._timeouts + 1 if a.failure == "timeout" or a.unreachable else 0
        self._answers[key] = a
        return a

    def _mask(self, q: Question) -> Question:
        from policypack.egress import mask

        code, c1 = mask(q.code)
        header, c2 = mask(q.header)
        for counts in (c1, c2):
            for k, v in counts.items():
                self.masked[k] = self.masked.get(k, 0) + v
        return dataclasses.replace(q, code=code, header=header) if c1 or c2 else q


# ── 응답 해석 ───────────────────────────────────────────────────────────────

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


def json_only(text: str) -> str:
    """첫 JSON 객체만 남긴다.

    CLI 판정자는 JSON 뒤에 설명을 덧붙인다. 그 설명 때문에 답을 버리면 '모름'이 경고로 남는다.
    중괄호 균형으로 잘라 낸다.
    """
    t = _FENCE.sub("", text or "").strip()
    i = t.find("{")
    if i < 0:
        return t
    return _balanced_from(t, i)


def _balanced_from(t: str, i: int) -> str:
    """t[i] 의 '{' 에서 시작해 균형이 맞는 곳까지. 문자열 안의 중괄호는 세지 않는다."""
    depth, in_str, esc = 0, False, False
    for j in range(i, len(t)):
        ch = t[j]
        if in_str:
            in_str, esc = (in_str and not (ch == '"' and not esc)), (ch == "\\" and not esc)
            continue
        if ch == '"':
            in_str, esc = True, False
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return t[i : j + 1]
    return t[i:]


def parse_answer(raw: str) -> tuple[RawAnswer, str, bool]:
    """(정규화한 답, 인용, 파싱 실패 여부).

    첫 JSON 객체가 답이 아니면, "answer" 키를 가진 객체 가운데 마지막 것을 읽는다. 판정자가 설명과
    코드 블록을 먼저 쓰고 끝에 JSON 을 붙이면, 첫 '{' 가 설명 속 코드의 중괄호라 답을 잃는다."""
    first = _load(json_only(raw))
    got = _normalize(first)
    if got is not None:
        return got
    text = raw or ""
    for i in range(len(text) - 1, -1, -1):
        if text[i] != "{":
            continue
        d = _load(_balanced_from(text, i))
        if isinstance(d, dict) and "answer" in d:
            got = _normalize(d)
            if got is not None:
                return got
    evidence = str(first.get("evidence") or "") if isinstance(first, dict) else ""
    return "?", evidence, True


def _load(text: str):
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None


#: 받는 답. 앞 글자로 고르지 않는다 — 'not sure'·'none'·'no idea'·'아니라고 단정하기 어려움' 이 '아니오'가 되어
#: 인용도 없이 규칙을 뺐다(실측). 여기 없는 답은 파싱 실패다.
ANSWERS: dict[str, RawAnswer] = {
    "예": "예",
    "네": "예",
    "yes": "예",
    "y": "예",
    "아니오": "아니오",
    "아니요": "아니오",
    "no": "아니오",
    "n": "아니오",
    "해당없음": "해당없음",
    "해당 없음": "해당없음",
    "n/a": "해당없음",
    "not applicable": "해당없음",
}


def _normalize(d) -> tuple[RawAnswer, str, bool] | None:
    if not isinstance(d, dict):
        return None
    ans = re.sub(r"[\s.!。]+$", "", str(d.get("answer", "")).strip().lower())
    norm = ANSWERS.get(ans)
    if norm is None:
        return None
    return norm, str(d.get("evidence") or ""), False
