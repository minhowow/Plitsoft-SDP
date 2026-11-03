"""정책 팩 해석기.

정적 조건은 한 번에 모아 돌리고, 결론이 나지 않는 곳에서만 AI를 부른다.
Semgrep 엔진은 고치지 않는다. 부품으로 쓸 뿐이다.

순서: ① 적용 판단(정적) ② 적용이 '모름'이면 적용 질문(applies-ai) ③ 강한 정적 대안이 풀지 못한 곳만
AI 대안 질문 ④ 판정. 언제 묻고 무엇을 판정에 넣는지는 planner 가 정한다. AI 의 '예'는 여기서 근거
관문(evidence.is_grounded)을 거친다 — 판정자 안이 아니라서 스텁·가짜 판정자도 같은 관문을 지난다.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from policypack.evaluate.kleene import FALSE, TRUE, UNKNOWN, Tri, and3, or3
from policypack.evaluate.planner import (
    considered_values,
    decide,
    needs_alternative_questions,
    needs_applicability_question,
)
from policypack.evidence import classify, is_grounded
from policypack.judge.base import Answer, Judge, Question
from policypack.model import Evidence, Policy, PolicyPack, Predicate, Rule, Scope, Strength
from policypack.report.outcome import Finding, Outcome, UntestedReason, reason_for_failure
from policypack.static.backend import PredicateKey, Span, StaticResult
from policypack.static.compile import GROUP_APPLIES, GROUP_COMPLIANT


@dataclass(frozen=True)
class Target:
    path: Path
    lang: str
    case: str | None = None

    @property
    def code(self) -> str:
        return self.path.read_text(encoding="utf-8", errors="replace")

    @property
    def raw_lines(self) -> list[str]:
        """semgrep 과 같은 방식으로 센 줄. '\n' 으로만 자른다.

        read_text 는 '\r' 을 줄바꿈으로 바꾸고, splitlines 는 U+2028·\f 에서도 자른다.
        그러면 semgrep 의 줄 번호로 자른 구역이 엉뚱한 줄을 가리킨다(실측)."""
        return self.path.read_bytes().decode("utf-8", errors="replace").split("\n")


@dataclass
class Unit:
    """판정 대상 하나 = (정책, 규칙, 파일)."""

    policy: Policy
    rule: Rule
    target: Target
    applies: Tri = TRUE
    alts: list[tuple[str, Predicate, Tri | None]] = field(default_factory=list)
    ai_alts: list[tuple[Predicate, Answer, Tri]] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    reasons: list[UntestedReason] = field(default_factory=list)
    """판정을 끝까지 하지 못한 이유(파싱 실패, 판정자 없음, 답 없음 …). 판정 종류와 상관없이 쌓인다."""
    pending: list[str] = field(default_factory=list)
    """AI 에게 물어야 했는데 판정에 넣을 답이 없는 조건 id('applies-ai' 또는 대안 id)."""
    unanswered: list[tuple[Predicate, str]] = field(default_factory=list)
    """판정에 넣지 않은 AI 대안과 그 까닭(판정자 없음·실패·스텁 없음·쓸 수 없는 답). 판정자가 없을 때와 같은
    결론이 나게 한다 — AI 답은 근거가 있을 때만 경고를 풀고, 근거 없는 답이 결론을 흐리지 못한다."""
    cited: dict[str, str] = field(default_factory=dict)
    """AI 대안 id → 관문을 통과한 인용이 코드의 어디에 있었는지(GateResult 값). AI 해제 기록에 쓴다."""
    anchor: Span | None = None
    """판정을 걸 위치. 적용 조건이 맞은 첫 매치를 쓴다.

    파일 단위 판정(scope: file)이라도 사람에게 보여 줄 때는 줄이 필요하다.
    SARIF region, pre-commit 피드백, 훅 메시지가 전부 '어느 줄'을 요구한다.
    실측: semgrep 은 로그인 여부와 무관하게 start/end 의 line·col·offset 을 항상 준다."""

    region: Span | None = None
    """scope: anchor 의 판정 구역 = 앵커를 감싸는 가장 바깥 함수. None 이면 파일 전체다."""
    anchors: list[Span] = field(default_factory=list)
    """이 구역 안에서 anchor-on 조건이 맞은 자리. 같은 구역의 앵커는 판정이 같을 수밖에 없어 묶는다."""
    outside: list[Span] = field(default_factory=list)
    """함수 밖(모듈 최상위) 구역이면 제외할 함수 span 들. 비어 있으면 함수 밖 구역이 아니다."""
    boundaries_lost: UntestedReason | None = None
    """함수 단위 규칙의 단위가 함수 구역이 아닌데(파일 전체, 함수 밖) 이 파일의 함수 경계를 믿을 수 없는 까닭.
    경계 실행이 실패했으면 ENGINE_INCOMPLETE, 파일이 다 파싱되지 않았으면 PARSE_ERROR 다. 이런 단위는 대안
    (정적 매치든 AI 인용이든)으로 '충족'이라 하지 않는다 — 엔진이 되찾지 못한 다른 함수의 가드일 수 있다."""

    @property
    def top_level(self) -> bool:
        return bool(self.outside)

    @property
    def answered(self) -> bool:
        """물은 AI 대안에 모두 답을 받았는가. 묻지 않았으면(강한 정적 대안이 풀었거나 AI 대안이 없으면) 거짓."""
        return bool(self.ai_alts) and not self.unanswered

    def add_reason(self, reason: UntestedReason) -> None:
        if reason not in self.reasons:
            self.reasons.append(reason)

    @property
    def narrowed(self) -> bool:
        """판정 구역이 파일 전체보다 좁은가(함수 구역이거나 함수 밖 구역)."""
        return self.region is not None or self.top_level

    @property
    def ref(self) -> str:
        return f"{self.policy.id}/{self.rule.id}"

    @property
    def group(self) -> tuple:
        """같은 질문을 공유하는 단위들의 열쇠. file 이면 단위 하나가 곧 그룹이다.

        경로가 아니라 Target 으로 묶는다. 같은 파일을 가리키는 Target 이 둘이면(정책 테스트의
        반사실 픽스처) 서로 다른 판정 대상이다."""
        return (self.policy.id, self.rule.id, self.target)

    @property
    def region_key(self) -> tuple:
        """같은 (정책, 규칙, 대상) 안에서 구역을 가르는 열쇠. 파일 단위면 빈 튜플."""
        if not self.narrowed:
            return ()
        if self.top_level:
            return ("top",)
        assert self.region is not None
        return (self.region.start.line, self.region.end.line)

    @property
    def alt_key(self) -> tuple:
        """대안 질문을 공유하는 단위의 열쇠. 구역마다 보내는 코드가 달라 구역까지 넣는다."""
        return self.group + self.region_key

    def prompt_code(self) -> str:
        """판정자에게 보낼 코드. 파일 단위면 파일 전체, 구역이면 근거 관문이 인용을 찾는 그 줄들이다.

        함수 밖 구역은 함수 본문을 비운 줄이 이어지므로 빈 줄 뭉치를 하나로 줄인다. 관문은 공백을
        정규화해 비교하므로 인용 판정에는 영향이 없다."""
        if not self.narrowed:
            return self.target.code
        return _squeeze_blank_lines(self.gate_code())

    def prompt_header(self) -> str:
        """함수 구역일 때 붙이는 같은 파일의 참고 줄. `file_header` 를 본다."""
        if self.region is None or self.top_level:
            return ""
        from policypack.evidence import strip_comments

        raw = self.target.raw_lines
        stripped = strip_comments("\n".join(raw)).split("\n")
        return file_header(raw, self.region, self.gate_code(), stripped)

    def fragment(self) -> str:
        """판정자에게 보내는 코드가 파일의 어느 부분인가. 파일 전체면 빈 문자열."""
        if not self.narrowed:
            return ""
        return "top-level" if self.top_level else "function"

    def gate_code(self) -> str:
        """근거 관문이 인용을 찾을 코드. 구역이 있으면 그 줄들만."""
        if not self.narrowed:
            return self.target.code
        return self._slice(self.target.raw_lines)

    def gate_stripped(self) -> str | None:
        """gate_code 에서 주석을 걷어 낸 것. 주석은 파일 전체에서 걷은 뒤 자른다.

        조각만 걷으면 조각 앞의 짝 없는 따옴표(JSX 글의 Don't 등)를 몰라서 주석을 코드로 읽는다.
        그러면 관문이 주석 인용을 받아 anchor 가 file 이 경고한 것을 풀어 버린다(검토에서 실측)."""
        if not self.narrowed:
            return None
        from policypack.evidence import strip_comments

        whole = "\n".join(self.target.raw_lines)
        return self._slice(strip_comments(whole).split("\n"))

    def _slice(self, lines: list[str]) -> str:
        if self.top_level:
            # 함수 밖 구역: 함수 안의 줄은 비운다(줄 번호는 그대로)
            part = ["" if _covered(i, self.outside) else line for i, line in enumerate(lines, 1)]
        else:
            assert self.region is not None
            part = lines[self.region.start.line - 1 : self.region.end.line]
        return "\n".join(line.rstrip("\r") for line in part)


def _squeeze_blank_lines(code: str) -> str:
    out: list[str] = []
    for line in code.split("\n"):
        if not line.strip() and out and not out[-1].strip():
            continue
        out.append(line)
    return "\n".join(out).strip("\n")


#: import 문. `import(` 와 `import.meta` 는 식이지 선언이 아니다.
_IMPORT = re.compile(r"""^import(?=[\s{*"'])""")
_REQUIRE = re.compile(r"^(?:export\s+)?(?:const|let|var)\s+([^=]+?)\s*=\s*require\(")
_TOP_DECL = re.compile(
    r"^(?:export\s+(?:default\s+)?)?(?:declare\s+)?(?:abstract\s+)?(?:async\s+)?"
    r"(?:const|let|var|function\*?|class|type|interface|enum)\s+([A-Za-z_$][\w$]*)"
)
_WORD = re.compile(r"[A-Za-z_$][\w$]*")
_STRING = re.compile(r"""(["'`])(?:\\.|(?!\1).)*\1""")
_IMPORT_WORDS = {"import", "type", "typeof", "as", "from", "require", "const", "let", "var", "export", "default"}
#: 구역 첫 줄에서 함수 이름을 읽는다. 이름이 없으면(익명 콜백) 부르는 줄을 찾지 않는다.
_REGION_NAME = (
    re.compile(r"\bfunction\s*\*?\s*([A-Za-z_$][\w$]*)"),
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]*)?=(?!=)"),
    re.compile(
        r"^\s*(?:(?:public|private|protected|static|async|override|readonly)\s+)*(?:get\s+|set\s+)?\*?\s*"
        r"([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\("
    ),
)
_NOT_A_NAME = {"if", "for", "while", "switch", "catch", "function", "return", "await", "new", "typeof"}
_THIS_READ = re.compile(r"\bthis\.([A-Za-z_$][\w$]*)\b(?!\s*\()")

#: 머리의 상한. 머리는 참고일 뿐이라 함수보다 커지면 안 된다.
HEADER_MAX_LINES = 60
HEADER_MAX_CHARS = 6000
#: 선언 하나에서 싣는 줄 수. 같은 파일 헬퍼의 본문이 보여야 이름만 그럴듯한 가드에 속지 않는다.
DECL_MAX_LINES = 12
#: 구역 함수를 부르는 줄과, 구역이 읽는 this 필드에 값을 넣는 줄의 상한.
CALLER_MAX_LINES = 5
FIELD_WRITE_MAX_LINES = 8
#: 익명 콜백 구역 앞에서 같은 문장에 속한 줄의 상한.
STATEMENT_HEAD_MAX_LINES = 8


def file_header(raw_lines: list[str], region: Span, region_code: str, stripped: list[str] | None = None) -> str:
    """함수 구역 판정에 붙일 같은 파일의 참고 줄. 우선순위 순서로 상한 안에서 고른다.

    1. 구역이 이름을 쓰는 최상위 선언(const·let·var·function·class·type·interface·enum). 본문까지
       `DECL_MAX_LINES` 줄. 첫 줄만 보내면 `function isQuietHours() { return false }` 같은 가짜 가드를
       판정자가 이름만 보고 믿는다(검토에서 흉내 판정자로 실측).
    2. 구역 함수를 부르는 줄(`CALLER_MAX_LINES`). 값이 어디서 오는지(`readDoc(req.query.name)`)가 여기 있다.
       구역이 이름 없는 콜백이면 대신 같은 문장의 앞줄(`STATEMENT_HEAD_MAX_LINES`)을 싣는다.
       `fs.readdirSync(d).filter(...)` 뒤의 `.forEach(function (file) {` 에서 file 이 어디서 오는지가 거기 있다.
    3. 구역이 읽는 `this.필드` 에 값을 넣는 줄(`FIELD_WRITE_MAX_LINES`).
    4. 구역이 쓰는 이름을 들여오는 import·require. 여러 줄 import 는 한 줄로 접는다.

    고른 뒤에는 파일 순서로 내보내고, 떨어진 조각 사이에 `// …` 를 둔다. 구역 줄은 넣지 않는다.
    파서 없이 줄로 본다. 참고 자료라 조금 모자라거나 넘쳐도 판정 범위(근거 관문)는 바뀌지 않는다.
    `stripped` 는 주석을 걷은 줄(같은 줄 수)이다. 주석 안의 `import`·선언을 머리로 읽지 않으려고 쓴다.
    """
    raw = [line.rstrip("\r") for line in raw_lines]
    code = stripped if stripped is not None and len(stripped) == len(raw) else raw
    code = [line.rstrip("\r") for line in code]
    n = len(raw)
    lo, hi = region.start.line - 1, region.end.line - 1  # 0부터 센 구역 줄

    def inside(i: int) -> bool:
        return lo <= i <= hi

    head, head_cut = _statement_head(code, lo, inside) if 0 <= lo < n else ([], False)
    # 앞줄이 쓰는 이름(fs 등)의 import 도 싣는다
    used = set(_WORD.findall(region_code)) | {w for k in head for w in _WORD.findall(code[k])}
    pieces: list[tuple[int, int, int, list[str]]] = []  # (우선순위, 첫 줄, 끝 줄, 내보낼 줄)
    taken: set[int] = set()
    if head:
        body = (["// …"] if head_cut else []) + [raw[k] for k in head]
        pieces.append((1, head[0], head[-1], body))
        taken.update(head)

    i = 0
    while i < n:
        if inside(i):
            i = hi + 1
            continue
        if i in taken:
            i += 1
            continue
        line = code[i]
        if _IMPORT.match(line):
            end = _import_end(code, i, inside)
            text = " ".join(part.strip() for part in raw[i : end + 1]) if end > i else raw[i]
            if (set(_WORD.findall(_STRING.sub("", " ".join(code[i : end + 1])))) - _IMPORT_WORDS) & used:
                pieces.append((3, i, end, [text]))
            taken.update(range(i, end + 1))
            i = end + 1
            continue
        m = _REQUIRE.match(line)
        if m:
            if (set(_WORD.findall(m.group(1))) - _IMPORT_WORDS) & used:
                pieces.append((3, i, i, [raw[i]]))
            taken.add(i)
            i += 1
            continue
        m = _TOP_DECL.match(line)
        if m and m.group(1) in used:
            idx, cut = _decl_lines(code, i, inside)
            body = [raw[k] for k in idx] + (["  // … (본문이 길어 줄였다)"] if cut else [])
            pieces.append((0, i, idx[-1], body))
            taken.update(idx)
            i = idx[-1] + 1
            continue
        i += 1

    name = _region_name(raw[lo] if 0 <= lo < n else "")
    if name:
        ref = re.compile(rf"(?<![\w$]){re.escape(name)}(?![\w$])")
        callers = [k for k in range(n) if not inside(k) and k not in taken and ref.search(code[k])]
        for k in callers[:CALLER_MAX_LINES]:
            pieces.append((1, k, k, [raw[k]]))
            taken.add(k)

    fields = {f for f in _THIS_READ.findall(region_code)}
    if fields:
        alt = "|".join(re.escape(f) for f in sorted(fields))
        write = re.compile(
            rf"\bthis\.(?:{alt})\s*(?:[-+*/|&?]?=(?![=>])|\.\s*(?:set|push|add|unshift|splice|assign)\s*\()"
        )
        writes = [k for k in range(n) if not inside(k) and k not in taken and write.search(code[k])]
        pieces.extend((2, k, k, [raw[k]]) for k in writes[:FIELD_WRITE_MAX_LINES])

    chosen: list[tuple[int, int, list[str]]] = []
    lines = chars = dropped = 0
    for _, start, last, body in sorted(pieces, key=lambda p: (p[0], p[1])):
        size = sum(len(x) + 1 for x in body)
        if lines + len(body) > HEADER_MAX_LINES or chars + size > HEADER_MAX_CHARS:
            dropped += len(body)
            continue
        chosen.append((start, last, body))
        lines += len(body)
        chars += size

    out: list[str] = []
    prev_end = None
    for start, last, body in sorted(chosen, key=lambda p: p[0]):
        if prev_end is not None and start != prev_end + 1 and body[0] != "// …":
            out.append("// …")
        out.extend(body)
        prev_end = last
    if dropped:
        out.append(f"// … (머리가 길어 {dropped}줄을 뺐다)")
    return "\n".join(out)


def _import_end(code: list[str], i: int, inside) -> int:
    """import 문이 끝나는 줄. `{` 로 열고 닫지 않은 import 만 이어 읽는다.

    세미콜론을 쓰지 않는 스타일에서 `import "x"` 뒤를 이어 읽으면 다음 함수 전체를 삼킨다(검토에서 실측).
    이어 읽다가 구역 줄이나 `}` 로 시작하지 않는 0열 줄을 만나면 import 가 아니었던 것으로 보고 첫 줄만 쓴다."""
    first = code[i]
    if "{" not in first or "}" in first[first.index("{") :]:
        return i
    j = i + 1
    while j < len(code) and j - i < 400:
        line = code[j]
        if inside(j) or (line[:1] not in (" ", "\t", "}", "") and line.strip()):
            return i
        if "}" in line:
            # `} ` 다음 줄에 `from "x"` 가 따로 오는 꼴
            split_from = j + 1 < len(code) and not inside(j + 1) and re.match(r"^\s*from\s", code[j + 1])
            return j + 1 if " from " not in f" {line} " and split_from else j
        j += 1
    return i


def _decl_lines(code: list[str], i: int, inside) -> tuple[list[int], bool]:
    """최상위 선언의 줄(첫 줄부터). 들여쓴 줄과 0열의 닫는 줄까지 읽는다. (줄, 잘렸는가)."""
    out = [i]
    if code[i].rstrip().endswith(";"):
        return out, False
    j = i + 1
    n = len(code)
    while j < n:
        if inside(j):
            return out, False
        line = code[j]
        if not line.strip():
            k = j + 1
            while k < n and not code[k].strip():
                k += 1
            if k >= n or inside(k) or not code[k][:1].isspace():
                return out, False
        elif not line[:1].isspace():
            if line.lstrip()[:1] in "})]":
                if len(out) >= DECL_MAX_LINES:
                    return out, True
                out.append(j)
            return out, False
        if len(out) >= DECL_MAX_LINES:
            return out, True
        out.append(j)
        j += 1
    return out, False


def _statement_head(code: list[str], lo: int, inside) -> tuple[list[int], bool]:
    """이름 없는 콜백 구역 바로 앞에서 같은 문장에 속한 줄. (줄, 잘렸는가).

    구역 첫 줄이 `.` 으로 시작하거나(메서드 체인), 앞줄이 `(`·`,` 로 끝나면(인자) 위로 올라간다.
    구역보다 덜 들여쓴 줄이 나오면 그것이 문장의 첫 줄이다. 빈 줄, 다른 구역, 앞 문장의 끝(`;`)에서 멈춘다."""
    if lo <= 0:
        return [], False
    first = code[lo]
    indent = len(first) - len(first.lstrip())
    if not (first.lstrip().startswith(".") or code[lo - 1].rstrip().endswith(("(", ","))):
        return [], False
    out: list[int] = []
    j = lo - 1
    while j >= 0:
        line = code[j]
        text = line.strip()
        if not text or inside(j):
            break
        depth = len(line) - len(line.lstrip())
        if text.endswith(";") and depth <= indent:
            break  # 앞 문장이 끝났다
        if len(out) >= STATEMENT_HEAD_MAX_LINES:
            return sorted(out), True
        out.append(j)
        if depth < indent and not text.startswith((".", "}", ")", "]")):
            break  # 문장의 첫 줄
        j -= 1
    return sorted(out), False


def _region_name(first_line: str) -> str | None:
    for k, pattern in enumerate(_REGION_NAME):
        if k == 2 and "=>" in first_line:
            break  # `useEffect(() => {` 는 메서드 정의가 아니라 호출이다
        m = pattern.search(first_line)
        if m and m.group(1) not in _NOT_A_NAME:
            return m.group(1)
    return None


@dataclass
class EvalResult:
    findings: list[Finding] = field(default_factory=list)
    units: list[Unit] = field(default_factory=list)
    judge_id: str = ""
    questions_asked: int = 0
    """판정자에게 넘긴 질문 수(답을 받지 못한 것 포함)."""
    ai_answered: int = 0
    """형식에 맞는 답을 받은 질문 수(관문이 받지 않은 답도 포함). 판정자가 실패했거나 스텁이 없는 질문은 빠진다."""
    questions_sent: int = 0
    """판정자에게 실제로 보낸 서로 다른 질문 수. 같은 질문은 한 실행에서 한 번만 보내므로(OncePerRun)
    questions_asked 보다 적을 수 있다. 어댑터 안의 재시도는 세지 않는다. cmd_scan 이 판정자에게서 받아 적는다."""
    questions_skipped: int = 0
    """판정자가 연달아 시간 안에 답하지 않아 보내지 않은 서로 다른 질문 수(questions_sent 와 같은 기준).
    cmd_scan 이 판정자에게서 받아 적는다."""
    ai_pending: int = 0
    """AI 에게 물어야 했는데 판정에 넣을 답이 없어 경고로 남은 판정 단위 수(판정자 없음 포함). 다른 대안이 풀어
    준수가 된 단위는 세지 않는다 — 답을 받았어도 결론이 바뀌지 않는다."""
    ai_cleared: list[dict] = field(default_factory=list)
    """AI 의 '예'로 경고가 풀린 단위. 규칙·파일·인용한 줄·관문 결과를 남겨 사람이 검토할 수 있게 한다."""
    ai_dismissed: list[dict] = field(default_factory=list)
    """적용 질문의 '아니오'로 판정 대상에서 빠진 단위. 인용 없이 빠지므로 흔적을 남긴다."""
    static_cleared: list[dict] = field(default_factory=list)
    """강한 정적 대안으로 경고가 풀린 단위. 규칙·파일·대안 id·맞은 줄 번호를 남긴다(코드는 싣지 않는다).
    경고가 없는 까닭이 '적용 신호 없음'인지 '충족 근거 발견'인지 보고서에서 가를 수 있게 한다.
    units = findings + ai_cleared + static_cleared 다."""
    static_seconds: float = 0.0
    engine: str = ""
    """정적 조건을 돌린 엔진과 판본(예: "semgrep 1.176.1"). 보고서에 싣는다 — 엔진이 바뀌면 결과가 달라질 수 있다."""
    ai_seconds: float = 0.0
    unparsed: list[str] = field(default_factory=list)
    """파싱하지 못한 판정 대상 파일. 그 파일의 구문 조건은 '모름'이 된다.

    사용자가 알아야 한다. 경고가 없다는 것이 "문제가 없다"가 아니라 "못 봤다"일 수 있다."""
    skipped: list[str] = field(default_factory=list)
    """검사하지 않은 파일(까닭은 discover.SKIPPED_REASONS)."""
    incomplete: list[str] = field(default_factory=list)
    """엔진이 정책 조건을 끝까지 돌리지 못했거나(시간 초과·메모리 부족 등) 함수 단위 규칙에 쓸 함수 경계를
    구하지 못한 판정 대상 파일. 파싱 실패와 다르다."""
    engine_errors: list[str] = field(default_factory=list)
    """엔진이 어느 파일인지 밝히지 않은 오류의 원문. 그 실행의 대상은 `incomplete` 에 들어 있다."""
    agent: dict | None = None
    """에이전트 검토 단계(`--agent`)의 기록(evaluate.agent_pass). 돌리지 않았으면 None 이고 보고서에 싣지 않는다."""

    @property
    def coverage_complete(self) -> bool:
        """검사하겠다고 한 것을 전부 봤는가. 아니면 '경고 없음'이 '문제 없음'을 뜻하지 않는다."""
        return not (self.unparsed or self.skipped or self.incomplete or self.engine_errors)


def static_value(pred: Predicate, key: PredicateKey, target: Target, static: StaticResult) -> Tri:
    """정적 조건 하나의 값.

    파일 전체가 Syntax error 면 언어가 붙은 정규식 규칙도 매치되지 않는다(실측). 그래서 컴파일러가
    정규식 조건의 generic 사본을 함께 내고, 그 사본이 매치하면 여기서 참이 된다.
    """
    path = target.path.resolve()
    if static.spans(key, path):
        return TRUE
    if static.unfinished(key, path):
        # 엔진이 이 조건을 끝까지 돌리지 못했다. 정규식 조건이어도 '매치 없음'을 믿지 않는다
        return UNKNOWN
    if path in static.unreliable_paths() and not pred.parse_independent:
        return UNKNOWN
    return FALSE


def _overlaps(a: Span, b: Span) -> bool:
    """줄 단위로 겹치는가. 구역은 줄 범위다 — 근거 관문도 줄로 인용을 찾는다."""
    return a.start.line <= b.end.line and b.start.line <= a.end.line


def static_value_in(
    pred: Predicate,
    key: PredicateKey,
    target: Target,
    static: StaticResult,
    region: Span | None,
    outside: list[Span] | None = None,
) -> Tri:
    """구역 안의 정적 조건 값. 구역이 없으면 static_value 와 같다.

    구역과 **겹치는** 매치만 참이다. 감싸는 매치(cron.schedule(..., () => { send }))도 겹치므로
    인정한다. 구역 밖에만 매치가 있으면 거짓이다 — 경고를 올리는 방향이다.
    """
    if region is None and not outside:
        return static_value(pred, key, target, static)
    path = target.path.resolve()
    mine = static.spans(key, path)
    if region is not None and any(_overlaps(span, region) for span in mine):
        return TRUE
    if outside and any(
        not _covered(line, outside) for span in mine for line in range(span.start.line, span.end.line + 1)
    ):
        # 함수 밖 구역: 매치가 함수 밖의 줄에 닿아야 한다. 다른 함수 안의 가드는 이 구역의 가드가 아니다
        return TRUE
    if static.unfinished(key, path):
        return UNKNOWN
    if path in static.unreliable_paths() and not pred.parse_independent:
        return UNKNOWN
    return FALSE


def _covered(line: int, functions: list[Span]) -> bool:
    return any(f.start.line <= line <= f.end.line for f in functions)


#: 함수 구역이 아닌 단위에서 함수 경계를 믿을 수 없는 까닭을 판정 경로에 적는 말
_BOUNDARIES_LOST = {
    UntestedReason.ENGINE_INCOMPLETE: "함수 경계를 얻지 못함",
    UntestedReason.PARSE_ERROR: "파싱되지 않은 곳이 있어 함수 경계를 믿지 못함",
}

#: 함수 밖(모듈 최상위) 앵커의 구역. 함수 안 앵커와 함께 있을 때만 쓴다.
TOP_LEVEL = "top-level"


def _regions_for(anchors: list[Span], functions: list[Span]) -> dict[Span | str | None, list[Span]]:
    """앵커 → 감싸는 가장 바깥 함수. 감싸는 함수가 없으면 None(파일 전체)."""
    out: dict[Span | None, list[Span]] = {}
    for a in sorted(set(anchors), key=lambda s: (s.start.offset, s.end.offset)):
        # 줄로 감싼다. `router.post("/signup", async (req, res) => {` 처럼 앵커가 함수와 같은 줄
        # 앞쪽에 있어도 그 함수 구역에 넣는다(오프셋으로 가르면 파일 전체 단위가 하나 더 생긴다).
        enclosing = [f for f in functions if f.start.line <= a.start.line and a.end.line <= f.end.line]
        outer = min(enclosing, key=lambda f: (f.start.line, -f.end.line)) if enclosing else None
        out.setdefault(outer, []).append(a)
    # 함수 안 앵커가 있으면, 함수 밖 앵커는 "함수 밖 줄" 구역으로 따로 판정한다. 파일 전체로
    # 판정하면 다른 함수 안의 가드가 모듈 최상위의 발송까지 풀어 준다(검토에서 실측).
    # 함수 안 앵커가 없으면 예전처럼 파일 전체 구역 하나다.
    if len(out) > 1 and None in out:
        out[TOP_LEVEL] = out.pop(None)
    return out


def _answer_to_tri(answer: Answer, code: str | None = None, strict: bool = False, stripped: str | None = None) -> Tri:
    """모델 답 → 세 값. 근거 관문이 여기서 적용된다(판정자 안이 아니라).

    `code` 를 주면 '예'는 그 코드에 실제로 있는 줄을 인용해야 참이다. 인용이 없거나 틀리면 '거짓'이 아니라
    '모름'이다 — 경고가 남는다. 대안 질문의 '모름'은 evaluate 가 판정에서 빼고 까닭을 남긴다. 적용 질문은
    `code` 없이 부른다. 적용의 '예'는 경고를 올리는 쪽이라 인용을 요구하지 않는다. '해당없음'과 '?'는 '모름'이다.
    """
    if answer.raw == "예":
        if code is None or is_grounded(answer.evidence, code, strict=strict, stripped=stripped):
            return TRUE
        return UNKNOWN
    if answer.raw == "아니오":
        return FALSE
    return UNKNOWN


def _rejection(a: Answer, u: Unit, strict: bool) -> str:
    """관문이 '예'의 인용을 받지 않은 까닭(evidence.GateResult 값 또는 '판정 구역 밖'). 보고서에 남겨 사람이 AI 의
    주장을 확인할 수 있게 한다."""
    if u.narrowed and _answer_to_tri(a, u.target.code, strict=strict) is TRUE:
        return "판정 구역 밖"
    return classify(a.evidence, u.gate_code(), stripped=u.gate_stripped()).value


def evaluate(pack: PolicyPack, targets: list[Target], static: StaticResult, judge: Judge | None = None) -> EvalResult:
    """팩을 대상에 적용한다. `judge` 가 없으면 AI 에게 물어야 할 곳을 'AI 확인 필요'로 남긴다.

    함수 단위(scope: anchor) 판정은 판정자에게 그 구역의 줄과 같은 파일의 참고 줄만 보내고, 구역마다 따로
    묻는다. 파일 전체를 보내면 큰 파일 하나가 한 회차 사용량의 상당 부분을 먹는다. 적용 질문은 파일 전체로
    묻는다(아래 ask_applies).
    """
    wanted = {t.path.resolve() for t in targets}
    result = EvalResult(
        unparsed=sorted(str(p) for p in static.unreliable if p.resolve() in wanted),
        judge_id=getattr(judge, "id", "") if judge else "",
        static_seconds=static.elapsed_s,
        engine=static.engine,
        incomplete=_unfinished_targets(targets, static),
        engine_errors=list(static.unlocated_errors),
    )

    unreliable = static.unreliable_paths()
    unfinished = static.unfinished_paths()
    # 파일마다 훑으면 파일 수의 제곱이 된다. 한 번만 만든다
    regions_by_path = {k.resolve(): v for k, v in static.regions.items()}
    lost = {p.resolve() for p in static.regions_failed}

    # ── 1. 적용 판단 (정적) ────────────────────────────────────────────────
    units: list[Unit] = []
    for policy, rule in pack.iter_rules():
        for target in targets:
            # applies-when 은 정적 조건만 받는다(문법이 AI 조건을 막는다)
            applies = and3(
                static_value(p, PredicateKey(policy.id, rule.id, GROUP_APPLIES, p.id), target, static)
                for p in rule.applies_when
            )
            if applies is FALSE:
                continue

            anchor = _anchor(policy, rule, target, static)
            note = ""
            if target.path.resolve() in unreliable:
                note += " (파일 일부가 파싱되지 않음)"
            if target.path.resolve() in unfinished:
                note += " (엔진이 이 파일에서 규칙을 끝내지 못함)"

            # file 이면 구역 하나(None). anchor 면 앵커를 감싸는 함수마다 하나. 앵커 매치가 하나도
            # 없으면 파일 전체 단위 하나로 되돌아간다 — file 이 내는 단위를 anchor 가 없애면 안 된다.
            regions: dict[Span | str | None, list[Span]] = {None: []}
            functions: list[Span] = []
            if rule.scope is Scope.ANCHOR:
                key = PredicateKey(policy.id, rule.id, GROUP_APPLIES, str(rule.anchor_on))
                path = target.path.resolve()
                spans = [m.span for m in static.matches if m.key == key and m.path.resolve() == path]
                functions = regions_by_path.get(path, [])
                if spans:
                    regions = _regions_for(spans, functions)

            for key_region, anchor_spans in regions.items():
                outside = functions if key_region == TOP_LEVEL else []
                region = key_region if isinstance(key_region, Span) else None
                alts: list[tuple[str, Predicate, Tri | None]] = [
                    ("ai", p, None)
                    if p.is_ai
                    else (
                        "static",
                        p,
                        static_value_in(
                            p,
                            PredicateKey(policy.id, rule.id, GROUP_COMPLIANT, p.id),
                            target,
                            static,
                            region,
                            outside,
                        ),
                    )
                    for p in rule.compliant_if_any
                ]
                # 함수 구역이 아닌 단위는 함수 경계를 믿을 수 있을 때만 푼다. 경계 실행이 실패했거나 파일이 다
                # 파싱되지 않았으면, 이 자리를 감싸는 함수를 엔진이 되찾지 못했을 수 있다(검토에서 실측: 함수 머리가
                # 파싱되지 않은 파일에서 다른 함수의 가드가 풀었다). 되찾은 함수 구역은 그대로 판정한다
                boundaries_lost = None
                if anchor_spans and region is None:
                    if target.path.resolve() in lost:
                        boundaries_lost = UntestedReason.ENGINE_INCOMPLETE
                    elif target.path.resolve() in unreliable:
                        boundaries_lost = UntestedReason.PARSE_ERROR
                where = ""
                if rule.scope is Scope.ANCHOR:
                    if region:
                        where = f" [구역 {region.start.line}~{region.end.line}행]"
                    else:
                        where = " [구역 함수 밖" if outside else " [구역 파일 전체"
                        where += f" — {_BOUNDARIES_LOST[boundaries_lost]}]" if boundaries_lost else "]"
                unit = Unit(
                    policy=policy,
                    rule=rule,
                    target=target,
                    applies=applies,
                    alts=alts,
                    trace=[f"적용: 정적 {applies}{note}{where}"],
                    anchor=anchor_spans[0] if anchor_spans else anchor,
                    region=region,
                    anchors=anchor_spans,
                    outside=outside,
                    boundaries_lost=boundaries_lost,
                )
                if target.path.resolve() in unfinished and applies is UNKNOWN:
                    unit.add_reason(UntestedReason.ENGINE_INCOMPLETE)
                elif target.path.resolve() in unreliable and applies is UNKNOWN:
                    unit.add_reason(UntestedReason.PARSE_ERROR)
                units.append(unit)

    def ask(q: Question) -> Answer:
        assert judge is not None
        result.questions_asked += 1
        a = judge.ask(q)
        result.ai_answered += 1 if a.failure is None else 0
        return a

    # ── 2. AI 1단계: 적용이 '모름'일 때만 묻는다 ──────────────────────────
    # 물을 곳은 판정자와 무관하게 정한다. 판정자가 없으면(기본값 --judge none) 묻지 않고 'AI 필요'로
    # 남긴다. 적용은 '모름'으로 남아 불확실로 보고된다.
    planned1 = [u for u in units if needs_applicability_question(u.applies, bool(u.rule.applies_ai))]
    stage1 = planned1 if judge is not None else []
    if judge is None:
        for u in planned1:
            u.pending.append("applies-ai")
            u.add_reason(UntestedReason.NO_JUDGE)
            u.trace.append("적용: AI 필요(판정자 없음) → unknown")

    def ask_applies(u: Unit) -> Answer:
        # 적용 여부는 파일 단위로 묻는다(구역 프롬프트여도). 적용 질문의 '아니오'는 인용 없이 규칙을
        # 끈다. 구역만 보고 묻자, 적용 근거가 같은 파일의 다른 함수에 있을 때 file 이 낸 경고를 anchor
        # 가 조용히 없앴다(흉내 판정자로 실측).
        assert u.rule.applies_ai is not None
        return ask(
            Question(
                text=u.rule.applies_ai.question,
                code=u.target.code,
                lang=u.target.lang,
                policy=u.policy.id,
                rule=u.rule.id,
                predicate="applies-ai",
                case=u.target.case,
            )
        )

    t0 = time.time()
    # 같은 (정책, 규칙, 대상)은 한 번만 묻는다
    by_group1 = {k: ask_applies(u) for k, u in _first_per_key(stage1, lambda u: u.group).items()}
    for u in stage1:
        a = by_group1[u.group]
        if a.failure is not None:
            # 답이 없으면 적용은 '모름' 그대로다. 판정자가 없을 때와 같다.
            # 판정자가 '모름'(?)이라고 답한 것은 실패가 아니다. 아래에서 '모름'으로 넣는다
            u.pending.append("applies-ai")
            u.add_reason(reason_for_failure(a.failure))
            u.trace.append(f"적용: AI 답 없음({a.failure}) → {u.applies}")
            continue
        u.applies = _answer_to_tri(a)
        u.trace.append(f"적용: AI {a.raw} → {u.applies}")
        if u.applies is UNKNOWN:
            # '해당없음'·'모름'은 적용을 정하지 못한다. 대안 질문처럼 판정자가 없을 때와 같이 두고 까닭을 남긴다
            u.pending.append("applies-ai")
            u.add_reason(UntestedReason.JUDGE_UNPARSEABLE)
        if u.applies is FALSE:
            # 인용 없이 단위가 빠진다. 사람이 볼 수 있게 남긴다
            result.ai_dismissed.append(
                {
                    "policy": u.policy.id,
                    "rule": u.rule.id,
                    "file": str(u.target.path),
                    "line": u.anchor.start.line if u.anchor else None,
                    "question": u.rule.applies_ai.question if u.rule.applies_ai else "",
                    "answer": a.raw,
                }
            )
    units = [u for u in units if u.applies is not FALSE]

    # ── 3. AI 2단계: 대안 ────────────────────────────────────────────────
    # 강한 정적 대안이 푼 곳과 물을 AI 대안이 없는 규칙은 묻지 않는다
    planned2 = [u for u in units if needs_alternative_questions(u.alts) and any(kind == "ai" for kind, _, _ in u.alts)]
    stage2 = planned2 if judge is not None else []
    if judge is None:
        for u in planned2:
            for kind, pred, _ in u.alts:
                if kind == "ai":
                    u.pending.append(pred.id)
                    u.unanswered.append((pred, "AI 필요(판정자 없음)"))
            u.add_reason(UntestedReason.NO_JUDGE)

    def ask_alts(u: Unit) -> list[tuple[Predicate, Answer]]:
        # 구역이면 판정자는 그 구역과 같은 파일의 참고 줄만 본다. 근거 관문이 인용을 찾는 범위와 같다
        code, header, fragment = u.prompt_code(), u.prompt_header(), u.fragment()
        out = []
        for kind, pred, _ in u.alts:
            if kind != "ai":
                continue
            assert pred.ai is not None
            q = Question(
                text=pred.ai.question,
                code=code,
                lang=u.target.lang,
                policy=u.policy.id,
                rule=u.rule.id,
                predicate=pred.id,
                case=u.target.case,
                header=header,
                fragment=fragment,
            )
            out.append((pred, ask(q)))
        return out

    # 같은 (정책, 규칙, 대상, 구역)은 한 번만 묻는다
    by_key2 = {k: ask_alts(u) for k, u in _first_per_key(stage2, lambda u: u.alt_key).items()}
    for u in stage2:
        for pred, a in by_key2[u.alt_key]:
            if a.failure is not None:
                # 판정자가 실패했거나 스텁이 없다. 판정자가 없을 때와 똑같이 판정에 넣지 않고 'AI 확인 필요'로
                # 남긴다 — 판정자가 고장 나도 없을 때보다 약한 결론이 나지 않는다. 판정자가 '모름'(?)이라고
                # 답한 것은 실패가 아니라 답이다 — 아래에서 '모름'으로 넣는다.
                u.pending.append(pred.id)
                u.add_reason(reason_for_failure(a.failure))
                u.unanswered.append((pred, f"AI 답 없음({a.failure})"))
                continue
            assert pred.ai is not None
            # strict 조건은 '이 문구가 코드에 실제로 있는가'를 묻는다. 줄 끝 주석이 붙은 인용도 받지 않는다
            strict = pred.ai.evidence is Evidence.STRICT
            value = _answer_to_tri(a, u.gate_code(), strict=strict, stripped=u.gate_stripped())
            if value is UNKNOWN:
                # 판정에 넣는 답은 '아니오'와 인용이 관문을 지난 '예'뿐이다. 나머지(인용이 틀린 '예', '해당없음',
                # '모름')는 판정자가 없을 때처럼 빼고 까닭을 남긴다. 넣으면 근거 없는 답 하나가 확실한 '검토 필요'를
                # '불확실'로 낮춰 --fail-on review 를 통과시켰다(끝까지 점검에서 실측)
                u.pending.append(pred.id)
                if a.raw == "예":
                    u.add_reason(UntestedReason.CITATION_REJECTED)
                    why = _rejection(a, u, strict)
                    u.unanswered.append((pred, f"AI 예 — 인용 불인정({why}): “{a.evidence[:120]}”"))
                else:
                    u.add_reason(UntestedReason.JUDGE_UNPARSEABLE)
                    u.unanswered.append((pred, f"AI {a.raw} — 대안 질문에 쓸 수 없는 답"))
                continue
            if value is TRUE:
                u.cited[pred.id] = classify(a.evidence, u.gate_code(), stripped=u.gate_stripped()).value
            u.ai_alts.append((pred, a, value))
    result.ai_seconds = time.time() - t0

    # ── 4. 판정 ──────────────────────────────────────────────────────────
    for u in units:
        for kind, pred, value in u.alts:
            if kind == "static":
                u.trace.append(f"대안 {pred.id}: 정적 {value}")
        for pred, a, value in u.ai_alts:
            u.trace.append(f"대안 {pred.id}: AI {a.raw} → {value}")
        for pred, why in u.unanswered:
            u.trace.append(f"대안 {pred.id}: {why} → 판정에 넣지 않음")

        _explain_weak(u)
        considered = considered_values(u.alts, [v for _, _, v in u.ai_alts], u.answered)
        compliant = or3(considered) if considered else FALSE
        outcome = decide(u.applies, compliant)
        if outcome is Outcome.COMPLIANT and u.boundaries_lost:
            # 맞은 대안이 이 발송을 감싸는 함수의 것인지 알 수 없다. 대안이 하나도 없을 때의 '검토 필요'는 그대로 둔다
            outcome = Outcome.NEEDS_REVIEW_UNCERTAIN
            u.add_reason(u.boundaries_lost)
            u.trace.append(f"{_BOUNDARIES_LOST[u.boundaries_lost]} — 다른 함수의 대안일 수 있어 풀지 않음")
        u.trace.append(f"→ {outcome.value}")

        if outcome is Outcome.COMPLIANT:
            cleared = _cleared_by_ai(u)
            if cleared:
                result.ai_cleared.append(cleared)
            else:
                result.static_cleared.append(_cleared_by_static(u, static))
            continue
        if u.pending:
            # 경고로 남은 단위만 센다. 다른 대안이 이미 풀었다면 물을 필요가 있었어도 결론은 바뀌지 않는다
            result.ai_pending += 1
        result.findings.append(
            Finding(
                policy=u.policy.id,
                rule=u.rule.id,
                outcome=outcome,
                file=str(u.target.path),
                case=u.target.case,
                category=u.policy.category,
                title=u.policy.title,
                law=_law_of(u.policy),
                ask_developer=u.policy.ask_developer or "",
                line=u.anchor.start.line if u.anchor else None,
                untested_reasons=list(u.reasons),
                ai_pending=list(u.pending),
                trace=list(u.trace),
                alternatives=_unsatisfied(u),
                **_where(u),
            )
        )

    result.units = units
    return result


def _first_per_key(units: list[Unit], key) -> dict[tuple, Unit]:
    """열쇠마다 첫 단위. 열쇠가 같은 단위는 같은 질문을 받으므로 한 번만 묻는다."""
    out: dict[tuple, Unit] = {}
    for u in units:
        out.setdefault(key(u), u)
    return out


def _explain_weak(u: Unit) -> None:
    """약한 대안의 '참'이 판정에서 어떻게 쓰였는지 흔적을 남긴다(considered_values 와 같은 규칙).

    약한 참은 AI 답으로 대신하거나, 답이 없으면 '모름'으로 낮춘다. 흔적이 없으면 trace 에는 '정적 true'만
    보이는데 결론은 불확실이라 사용자가 까닭을 알 수 없다.
    """
    has_ai = any(kind == "ai" for kind, _, _ in u.alts)
    for kind, pred, value in u.alts:
        if kind != "static" or pred.strength is not Strength.WEAK or value is not TRUE:
            continue
        if u.answered:
            u.trace.append(f"대안 {pred.id}: 약한 근거 — AI 답으로 대신함")
            continue
        u.trace.append(f"대안 {pred.id}: 약한 근거 — AI 확인 전에는 풀지 않음 → unknown")
        if not has_ai:
            u.add_reason(UntestedReason.WEAK_UNCONFIRMED)


def _cleared_by_ai(u: Unit) -> dict | None:
    """AI 의 '예'가 없었다면 경고가 났을 단위면, 사람이 검토할 기록을 만든다.

    관문은 인용한 줄이 코드에 **있는지만** 본다. 규칙과 관련 있는 줄인지는 보지 않는다. 그래서 AI 가
    푼 경고는 결과에 남겨야 한다 — 남기지 않으면 사람이 AI 의 해제를 검토할 방법이 없다.
    """
    yes = [(pred, a) for pred, a, value in u.ai_alts if value is TRUE]
    if not yes:
        return None  # 정적 대안이 풀었다
    return {
        "policy": u.policy.id,
        "rule": u.rule.id,
        "file": str(u.target.path),
        "line": u.anchor.start.line if u.anchor else None,
        "alternatives": [{"id": pred.id, "cite": a.evidence, "gate": u.cited.get(pred.id, "")} for pred, a in yes],
    }


def _cleared_by_static(u: Unit, static: StaticResult) -> dict:
    """강한 정적 대안이 푼 단위의 기록. 줄 번호만 싣는다 — 판정자 없이 낸 보고서에는 검사한 코드가 없다."""
    return {
        "policy": u.policy.id,
        "rule": u.rule.id,
        "file": str(u.target.path),
        "line": u.anchor.start.line if u.anchor else None,
        "alternatives": [
            {"id": pred.id, "lines": _match_lines(u, pred, static)}
            for kind, pred, value in u.alts
            if kind == "static" and value is TRUE and pred.strength is Strength.STRONG
        ],
    }


def _match_lines(u: Unit, pred: Predicate, static: StaticResult) -> list[int]:
    """이 단위의 구역에서 대안이 맞은 자리의 첫 줄. static_value_in 이 참으로 본 매치와 같은 것을 고른다."""
    spans = static.spans(PredicateKey(u.policy.id, u.rule.id, GROUP_COMPLIANT, pred.id), u.target.path.resolve())
    if u.region is not None:
        spans = [s for s in spans if _overlaps(s, u.region)]
    elif u.outside:
        spans = [s for s in spans if any(not _covered(n, u.outside) for n in range(s.start.line, s.end.line + 1))]
    return sorted({s.start.line for s in spans})


def _unfinished_targets(targets: list[Target], static: StaticResult) -> list[str]:
    """엔진이 조건을 끝내지 못했거나 함수 경계를 구하지 못한 판정 대상 파일. 대상이 받은 경로 그대로(보고서가
    상대 경로로 바꾼다)."""
    unfinished = static.unfinished_paths() | {p.resolve() for p in static.regions_failed}
    return sorted({str(t.path) for t in targets if t.path.resolve() in unfinished})


def _where(u: Unit) -> dict:
    """판정이 가리키는 곳. file 판정은 지금까지와 같다(아무것도 더하지 않는다)."""
    if u.rule.scope is not Scope.ANCHOR:
        return {}
    return {
        "scope": "anchor",
        "region": (u.region.start.line, u.region.end.line) if u.region else None,
        "top_level": u.top_level,
        "anchor_lines": sorted({s.start.line for s in u.anchors}),
    }


def _anchor(policy: Policy, rule: Rule, target: Target, static: StaticResult) -> Span | None:
    """적용 조건이 맞은 매치 중 가장 앞선 것.

    적용 조건이 없거나 정규식만으로 맞았으면 매치가 없을 수 있다. 그때는 None 이고,
    보고할 때 파일 전체를 가리킨다.
    """
    path = target.path.resolve()
    spans = [
        span
        for p in rule.applies_when
        for span in static.spans(PredicateKey(policy.id, rule.id, GROUP_APPLIES, p.id), path)
    ]
    return min(spans, key=lambda s: (s.start.line, s.start.col)) if spans else None


def _law_of(policy: Policy) -> str:
    if policy.legal and policy.legal.violated_when_failed:
        ref = policy.legal.violated_when_failed[0]
        return f"{ref.statute} {ref.article}" + (f" {ref.clause}" if ref.clause else "")
    return ""


def _unsatisfied(unit: Unit) -> list[dict]:
    """참이 아닌 대안마다 '왜 아닌지'와 개발자에게 할 질문.

    Kyverno 의 anyPattern 은 "여러 형태 중 하나"는 표현하지만 어느 것이 왜 안 맞았는지는
    말해 주지 못한다. 대안마다 따로 적어 두면 그걸 말할 수 있다.
    """
    values = {pred.id: value for _, pred, value in unit.alts if value is not None}
    values.update({pred.id: value for pred, _, value in unit.ai_alts})
    out = []
    for kind, pred, _ in unit.alts:
        # 묻지 않은 AI 대안을 "찾지 못했다"고 적으면 안 된다. 평가하지 않았을 뿐이다.
        if kind == "ai" and pred.id not in values:
            continue
        if values.get(pred.id) is TRUE or pred.on_unsatisfied is None:
            continue
        out.append(
            {
                "id": pred.id,
                "message": pred.on_unsatisfied.message,
                "ask_developer": pred.on_unsatisfied.ask_developer,
                "remediation": pred.on_unsatisfied.remediation,
                "value": str(values.get(pred.id, UNKNOWN)),
            }
        )
    return out
