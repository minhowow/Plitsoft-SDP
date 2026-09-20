"""세 값 논리 (Kleene).

조건의 값은 참·거짓·모름 셋이다. '모름'은 "아직 안 물어봤다"와 "물어봤는데 알 수 없다"를
같이 담는다. 둘을 가르는 것은 판정 경로(trace)의 일이고, 여기서는 값만 다룬다.

의존성이 없다. 이 모듈은 아무것도 import 하지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum


class Tri(str, Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"

    def __str__(self) -> str:  # 로그와 판정 경로에서 그대로 읽히게
        return self.value


TRUE, FALSE, UNKNOWN = Tri.TRUE, Tri.FALSE, Tri.UNKNOWN


def and3(values: Iterable[Tri]) -> Tri:
    """하나라도 거짓이면 거짓. 거짓이 없고 모름이 있으면 모름.

    빈 목록은 참이다. 적용 조건이 없는 규칙은 항상 적용된다는 뜻이다.
    """
    seen_unknown = False
    for v in values:
        if v is Tri.FALSE:
            return Tri.FALSE
        if v is Tri.UNKNOWN:
            seen_unknown = True
    return Tri.UNKNOWN if seen_unknown else Tri.TRUE


def or3(values: Iterable[Tri]) -> Tri:
    """하나라도 참이면 참. 참이 없고 모름이 있으면 모름.

    빈 목록은 거짓이다. 적법한 대안이 하나도 없으면 준수가 아니라는 뜻이다.
    """
    seen_unknown = False
    for v in values:
        if v is Tri.TRUE:
            return Tri.TRUE
        if v is Tri.UNKNOWN:
            seen_unknown = True
    return Tri.UNKNOWN if seen_unknown else Tri.FALSE


def clear_only(v: Tri) -> Tri:
    """참을 모름으로 낮춘다.

    약한 대안이 참이라는 것만으로 경고를 완전히 해제하지는 못하게 할 때 쓴다.
    결과는 '준수'가 아니라 '검토 필요(불확실)'가 된다.
    """
    return Tri.UNKNOWN if v is Tri.TRUE else v
