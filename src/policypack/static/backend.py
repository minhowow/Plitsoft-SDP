"""정적 백엔드가 주고받는 값.

백엔드는 Semgrep 이든 Opengrep 이든 이 모양으로만 말한다. 해석기는 백엔드가
무엇인지 몰라야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Pos:
    line: int
    col: int
    offset: int


@dataclass(frozen=True)
class Span:
    start: Pos
    end: Pos


@dataclass(frozen=True)
class PredicateKey:
    """조건 하나를 가리키는 안정적인 이름.

    매치는 check_id 가 아니라 규칙 metadata 로 되짚는다. semgrep 이 metadata 를 JSON 에
    그대로 실어 주기 때문이다(실측). check_id 에는 설정 파일 경로가 붙는다.
    """

    policy: str
    rule: str
    group: str  # "applies-when" | "compliant-if-any"
    predicate: str

    def __str__(self) -> str:
        return f"{self.policy}/{self.rule}/{self.predicate}"


@dataclass(frozen=True)
class Match:
    key: PredicateKey
    path: Path
    span: Span


@dataclass
class StaticResult:
    matches: list[Match] = field(default_factory=list)
    hard_unparsed: set[Path] = field(default_factory=set)
    """파일 전체를 파싱하지 못했다. 구문 패턴은 물론이고 **언어가 붙은 정규식 패턴도**
    매치되지 않는다(실측). 그래서 이런 파일에서는 generic 사본만 값을 낸다."""

    partial_unparsed: dict[Path, list[Span]] = field(default_factory=dict)
    """파일 일부만 파싱하지 못했다. 나머지 부분의 매치는 유효하다."""

    regions: dict[Path, list[Span]] = field(default_factory=dict)
    """함수 경계. scope: anchor 규칙이 있을 때만 컴파일된다. 파일 → 함수 span."""

    rule_timeouts: dict[Path, list[str]] = field(default_factory=dict)
    """규칙이 그 파일에서 시간 초과나 메모리 부족으로 끝나지 않았다. 파일 → 규칙 id."""

    rule_errors: list[str] = field(default_factory=list)
    """정책 팩이 만든 규칙 자체가 잘못됐다. 이건 사용자 코드 문제가 아니라 우리 문제다."""

    unlocated_errors: list[str] = field(default_factory=list)
    """파일 단위 오류(시간 초과, 메모리 부족 등)인데 엔진이 어느 파일인지 밝히지 않았다. 백엔드는 그 실행의
    대상 전체를 `incomplete` 로 둔다. 버리면 '모름'이 조용히 '거짓'이 된다."""

    incomplete: set[Path] = field(default_factory=set)
    """엔진이 이 파일에서 우리 규칙을 다 돌리지 못했다(시간 초과가 문턱에 닿아 나머지를 건너뜀, 어느 규칙인지
    모르는 시간 초과, 어느 파일인지 모르는 오류). 매치가 없는 조건은 정규식 조건까지 전부 '모름'이다.
    `hard_unparsed`(파싱 실패)와 다르다 — 파싱 실패여도 generic 정규식 사본은 끝까지 돌아 믿을 수 있다."""

    predicate_timeouts: dict[Path, list[PredicateKey]] = field(default_factory=dict)
    """이 파일에서 시간 초과로 끝나지 않은 정책 조건. 매치가 없어도 그 조건만 '모름'이다(정규식 조건 포함)."""

    runs: int = 0
    """엔진을 부른 횟수. 대상이 많으면 나눠 부른다."""

    elapsed_s: float = 0.0
    backend: str = ""
    backend_version: str = ""

    #: 아래 둘은 캐시다. 필드를 훑는 absorb 는 밑줄로 시작하는 이름을 건너뛴다.
    _index: dict | None = field(default=None, repr=False, compare=False)
    _unreliable: set | None = field(default=None, repr=False, compare=False)
    _unfinished: dict | None = field(default=None, repr=False, compare=False)

    def index(self) -> dict[PredicateKey, dict[Path, list[Span]]]:
        """조건 → (해석된 경로 → 매치 span 들). 한 번만 만들고 다시 쓴다.

        이게 없으면 조건 값을 물을 때마다 전체 매치를 훑고 경로를 resolve 한다. 판정 단위 ×
        조건 × 매치라 파일 수의 제곱으로 느려졌다(실측: 50개 0.23초, 100개 0.96초, 200개 3.28초).
        """
        if self._index is None:
            idx: dict[PredicateKey, dict[Path, list[Span]]] = {}
            for m in self.matches:
                idx.setdefault(m.key, {}).setdefault(m.path.resolve(), []).append(m.span)
            self._index = idx
        return self._index

    def spans(self, key: PredicateKey, resolved_path: Path) -> list[Span]:
        return self.index().get(key, {}).get(resolved_path, [])

    def unreliable_paths(self) -> set[Path]:
        """`unreliable` 을 해석된 경로로. 이것도 한 번만 만든다."""
        if self._unreliable is None:
            self._unreliable = {p.resolve() for p in self.unreliable}
        return self._unreliable

    def unfinished(self, key: PredicateKey, resolved_path: Path) -> bool:
        """엔진이 이 파일에서 이 조건을 끝까지 보지 못했는가. 그렇다면 '매치 없음'은 '거짓'이 아니다."""
        return key in self.unfinished_index().get(resolved_path, ()) or resolved_path in self.unfinished_index()[None]

    def unfinished_index(self) -> dict:
        """해석된 경로 → 끝나지 않은 조건들. 키 None 은 모든 조건이 끝나지 않은 파일의 집합이다."""
        if self._unfinished is None:
            idx: dict = {None: {p.resolve() for p in self.incomplete}}
            for p, keys in self.predicate_timeouts.items():
                idx.setdefault(p.resolve(), set()).update(keys)
            self._unfinished = idx
        return self._unfinished

    def unfinished_paths(self) -> set[Path]:
        """엔진이 조건을 하나라도 끝내지 못한 파일(해석된 경로)."""
        idx = self.unfinished_index()
        return set(idx[None]) | {p for p in idx if p is not None}

    def absorb(self, other: StaticResult) -> None:
        """나눠 돌린 실행의 결과를 합친다.

        필드를 손으로 나열하면 새 필드를 빠뜨린다. 빠뜨린 필드는 큰 저장소(나눠 돌린 실행)에서만
        말없이 사라진다. 그래서 필드를 훑어서 합치고, 합치는 법을 모르는 필드는 예외를 낸다.
        """
        self._index = self._unreliable = self._unfinished = None  # 합치면 캐시는 버린다
        for f in fields(self):
            if f.name in ("backend", "backend_version") or f.name.startswith("_"):
                continue
            mine, theirs = getattr(self, f.name), getattr(other, f.name)
            if isinstance(mine, list):
                mine.extend(theirs)
            elif isinstance(mine, set):
                mine |= theirs
            elif isinstance(mine, dict):
                for k, v in theirs.items():
                    mine.setdefault(k, []).extend(v)
            elif isinstance(mine, (int, float)) and not isinstance(mine, bool):
                setattr(self, f.name, mine + theirs)
            else:
                raise TypeError(f"StaticResult.{f.name} 을 합치는 법을 모른다")

    @property
    def engine(self) -> str:
        """보고서에 적을 엔진 이름과 판본. 예: "semgrep 1.176.1"."""
        return f"{self.backend} {self.backend_version}".strip()

    @property
    def unreliable(self) -> set[Path]:
        """구문 패턴의 '거짓'을 믿을 수 없는 파일.

        파일 전체가 파싱되지 않았으면 당연하고, **일부만 파싱되지 않은 경우도
        마찬가지다.** 파싱하지 못한 영역에 그 패턴이 있었을 수 있기 때문이다.
        여기서 '모름'을 내지 않으면 규칙이 조용히 꺼진다.
        """
        return self.hard_unparsed | set(self.partial_unparsed)


class StaticBackend(Protocol):
    name: str

    def version(self) -> str: ...

    def run(self, config: dict, targets: list[Path]) -> StaticResult: ...
