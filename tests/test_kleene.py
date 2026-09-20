"""세 값 논리 진리표 전수 검사.

이 모듈이 틀리면 모든 판정이 틀린다. 그래서 전수로 본다.
"""

from __future__ import annotations

import itertools

import pytest

from policypack.evaluate.kleene import FALSE, TRUE, UNKNOWN, Tri, and3, clear_only, or3

ALL = [TRUE, FALSE, UNKNOWN]


def test_empty_and_is_true():
    """적용 조건이 없는 규칙은 항상 적용된다."""
    assert and3([]) is TRUE


def test_empty_or_is_false():
    """적법한 대안이 하나도 없으면 준수가 아니다."""
    assert or3([]) is FALSE


@pytest.mark.parametrize("v", ALL)
def test_singleton(v):
    assert and3([v]) is v
    assert or3([v]) is v


@pytest.mark.parametrize("a,b", list(itertools.product(ALL, repeat=2)))
def test_and_truth_table(a, b):
    got = and3([a, b])
    if a is FALSE or b is FALSE:
        assert got is FALSE, "하나라도 거짓이면 거짓"
    elif a is UNKNOWN or b is UNKNOWN:
        assert got is UNKNOWN, "거짓이 없고 모름이 있으면 모름"
    else:
        assert got is TRUE


@pytest.mark.parametrize("a,b", list(itertools.product(ALL, repeat=2)))
def test_or_truth_table(a, b):
    got = or3([a, b])
    if a is TRUE or b is TRUE:
        assert got is TRUE, "하나라도 참이면 참"
    elif a is UNKNOWN or b is UNKNOWN:
        assert got is UNKNOWN
    else:
        assert got is FALSE


@pytest.mark.parametrize("a,b,c", list(itertools.product(ALL, repeat=3)))
def test_associative_and_commutative(a, b, c):
    """순서와 묶는 방식이 판정을 바꾸면 안 된다.

    조건을 평가하는 순서는 지연 평가 때문에 실행마다 달라질 수 있다.
    """
    assert and3([a, b, c]) is and3([c, b, a])
    assert and3([a, b, c]) is and3([and3([a, b]), c])
    assert or3([a, b, c]) is or3([c, b, a])
    assert or3([a, b, c]) is or3([or3([a, b]), c])


@pytest.mark.parametrize("a,b", list(itertools.product(ALL, repeat=2)))
def test_de_morgan(a, b):
    """드모르간이 성립한다 — Kleene 논리가 맞게 구현됐다는 교차 확인."""
    neg = {TRUE: FALSE, FALSE: TRUE, UNKNOWN: UNKNOWN}
    assert neg[and3([a, b])] is or3([neg[a], neg[b]])


def test_short_circuit_does_not_consume_rest():
    """and3 는 거짓을 만나면 남은 것을 보지 않는다."""
    seen = []

    def gen():
        for v in [TRUE, FALSE, TRUE]:
            seen.append(v)
            yield v

    assert and3(gen()) is FALSE
    assert seen == [TRUE, FALSE], "거짓 뒤의 조건은 평가되지 않아야 한다"


def test_or_short_circuit():
    seen = []

    def gen():
        for v in [FALSE, TRUE, FALSE]:
            seen.append(v)
            yield v

    assert or3(gen()) is TRUE
    assert seen == [FALSE, TRUE]


# ── 방향성 신뢰 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("v", ALL)
def test_clear_only_never_clears(v):
    """clear_only 는 참을 모름으로 낮춘다. 약한 대안의 참이 혼자 경고를 풀지 못하게 할 때 쓴다."""
    got = clear_only(v)
    assert got is not TRUE
    if v is FALSE:
        assert got is FALSE, "거짓은 그대로"


def test_weak_alternative_cannot_produce_compliance():
    """약한 대안만 참이면 결과는 준수가 아니라 모름이어야 한다.

    guardian-call 처럼 이름만 보는 대안이 '준수'를 확정하면,
    return true 만 하는 가짜 헬퍼에 속는다.
    """
    weak_true, strong_false = clear_only(TRUE), FALSE
    assert or3([weak_true, strong_false]) is UNKNOWN


# ── 표기 ────────────────────────────────────────────────────────────────────


def test_str_is_stable():
    """판정 경로와 보고서에 그대로 찍힌다."""
    assert [str(v) for v in ALL] == ["true", "false", "unknown"]
    assert Tri("unknown") is UNKNOWN
