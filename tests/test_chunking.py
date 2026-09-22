"""semgrep 을 여러 번에 나눠 돌려도 결과가 같아야 한다.

파일이 1500개를 넘으면 명령줄 길이 때문에 나눠 부른다. 합칠 때 필드를 손으로 나열했다가
필드를 빠뜨린 적이 있다. 1501파일 저장소에서 경고가 '검토할 것 없음', exit 0 으로 통과했다.
그래서 필드를 훑어 합치고, 합치는 법을 모르는 필드는 예외를 낸다.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from policypack.cli import main
from policypack.model import Rule
from policypack.pack.loader import load_pack
from policypack.static.backend import StaticResult
from policypack.static.compile import compile_static
from policypack.static.semgrep_cli import SemgrepBackend

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "policies" / "kr-core" / "tests"
VIOLATING = FIX / "pipa-22-2" / "violating.ts"


def _canon(res: StaticResult) -> dict:
    """비교할 수 있는 모양으로. 실행 시간과 순서는 뺀다."""
    return {
        "matches": sorted((str(m.key), str(m.path), m.span.start.offset) for m in res.matches),
        "regions": sorted((str(p), s.start.offset) for p, spans in res.regions.items() for s in spans),
        "hard": sorted(map(str, res.hard_unparsed)),
        "partial": sorted(map(str, res.partial_unparsed)),
        "timeouts": sorted((str(p), tuple(r)) for p, r in res.rule_timeouts.items()),
        "incomplete": sorted(map(str, res.incomplete)),
        "predicate_timeouts": sorted((str(p), tuple(map(str, k))) for p, k in res.predicate_timeouts.items()),
        "unlocated": sorted(res.unlocated_errors),
    }


def _with_an_anchor_rule(pack):
    """함수 경계 규칙도 나눠 돌리는 비교에 들어가게 50-3 규칙 하나를 scope: anchor 로 바꾼다."""
    pol = next(p for p in pack.policies if p.id == "kr.network-act.50-3")
    raw = {**pol.rules[0].model_dump(by_alias=True, exclude_none=True), "scope": "anchor", "anchor-on": "send-call"}
    pol = pol.model_copy(update={"rules": [Rule.model_validate(raw)]})
    return pack.model_copy(update={"policies": [pol if p.id == pol.id else p for p in pack.policies]})


def test_chunked_run_equals_single_run(monkeypatch):
    cfg = compile_static(_with_an_anchor_rule(load_pack(REPO / "policies/kr-core")))
    files = [VIOLATING, FIX / "pipa-22-2" / "under14-branch.ts", REPO / "tests/data/anchor/ads-mixed.tsx"]

    whole = SemgrepBackend().run(cfg, files)
    monkeypatch.setattr(SemgrepBackend, "CHUNK", 1)
    parts = SemgrepBackend().run(cfg, files)

    assert whole.matches and whole.regions, "비교가 의미 있으려면 매치와 함수 경계가 둘 다 있어야 한다"
    assert _canon(parts) == _canon(whole)


#: 합치지 않는 필드. backend 는 그대로 두고, 밑줄로 시작하는 것은 캐시라 버린다.
NOT_MERGED = ("backend", "backend_version")


def _merged_fields():
    return [f for f in dataclasses.fields(StaticResult) if f.name not in NOT_MERGED and not f.name.startswith("_")]


def test_absorb_covers_every_field():
    """새 필드를 더하고 합치는 법을 잊으면 여기서 바로 드러난다."""
    a, b = StaticResult(), StaticResult()
    for f in _merged_fields():
        value = getattr(b, f.name)
        if isinstance(value, list):
            value.append(object())
        elif isinstance(value, set):
            value.add(Path(f"/x/{f.name}"))
        elif isinstance(value, dict):
            value[Path(f"/x/{f.name}")] = [object()]
        elif isinstance(value, float):
            setattr(b, f.name, 1.5)
        elif isinstance(value, int):
            setattr(b, f.name, 2)
    a.absorb(b)
    for f in _merged_fields():
        assert getattr(a, f.name), f"{f.name} 이 합쳐지지 않았다"


def test_absorb_drops_the_lookup_cache():
    """색인을 만든 뒤 합치면 옛 색인이 남으면 안 된다. 남으면 뒤 청크의 매치가 보이지 않는다."""
    from policypack.static.backend import Match, Pos, PredicateKey, Span

    key = PredicateKey("p", "r", "applies-when", "c")
    a, b = StaticResult(), StaticResult()
    a.index()  # 비어 있는 상태로 색인을 만든다
    b.matches.append(Match(key=key, path=Path("/x/a.ts"), span=Span(Pos(1, 1, 0), Pos(1, 2, 1))))
    a.absorb(b)
    assert a.spans(key, Path("/x/a.ts").resolve())


def test_cli_still_catches_a_violation_when_chunked(tmp_path, monkeypatch, capsys):
    for i in range(3):
        (tmp_path / f"m{i}.js").write_text(f"export function f{i}(a) {{ return a + {i}; }}\n", encoding="utf-8")
    (tmp_path / "app.ts").write_text(VIOLATING.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(SemgrepBackend, "CHUNK", 1)
    code = main(["scan", ".", "--no-color", "--output-format", "concise"])
    out = capsys.readouterr().out
    assert code == 1, out
    assert "app.ts" in out and "만 14세" in out
