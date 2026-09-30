"""Semgrep JSON 출력을 StaticResult 로 옮긴다.

## 오류를 가르는 방식이 왜 이렇게 생겼나

`errors[]` 를 "path 가 있으면 파일 문제, 없으면 규칙 문제"로 가르면 안 된다. **PartialParsing
오류에는 최상위 path 키가 없다**(실측). 경로가 `type` 안의 스팬 목록에 중첩돼 있다. 그렇게 가르면
파일 일부가 파싱되지 않는 평범한 저장소를 스캔할 때 "정책 팩의 정적 조건 오류"라며 즉시 터진다.

여기서는 `type` 을 명시적으로 분기한다. semgrep 내부 구현에 우연히 기대지 않는다.

## 파싱 실패와 정규식의 관계 (실측)

파일 전체가 `Syntax error` 면 **언어가 붙은 정규식 규칙도 매치되지 않는다.** 파일이
통째로 버려지기 때문이다. `languages: [generic]` 인 규칙만 살아남는다. 그래서
`compile` 이 정규식 조건의 generic 사본을 함께 만들고, 평가기는 hard_unparsed 파일에서
그 사본의 결과만 본다.

`PartialParsing` 은 다르다. 파싱된 부분의 매치는 그대로 유효하다.

## 시간 초과는 규칙 하나의 일이다

`Timeout` 오류에는 `rule_id` 가 붙는다. 그 규칙이 그 파일에서 끝나지 않았다는 뜻이지
파일을 못 읽었다는 뜻이 아니다. 그래서 시간 초과가 난 정책 조건만 '모름'으로 둔다. 한 파일에서
시간 초과가 `TIMEOUT_THRESHOLD` 번 나면 semgrep 이 **나머지 규칙을 오류 없이 건너뛰므로**(실측)
그때는 파일 전체를 믿지 않는다. 함수 경계 규칙의 시간 초과는 그 파일을 파일 단위로 판정하게 할 뿐이다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, NamedTuple

from policypack.static.backend import Match, Pos, PredicateKey, Span, StaticResult
from policypack.static.compile import REGION_MARKER

#: 파일을 파싱하지 못한 오류. 구문 패턴의 값은 '모름'이 되지만 generic 정규식 사본은 믿는다.
#: 이름은 semgrep_output_v1 의 error_type 문자열 그대로다(semgrep 1.176.1 에서 확인).
PARSE_ERRORS = {"Syntax error", "Lexical error", "Other syntax error", "AST builder error", "PartialParsing"}

#: 규칙 하나가 파일 하나에서 끝나지 않았거나 결과가 잘린 오류. rule_id 와 path 가 붙어 온다.
RULE_LEVEL_ERRORS = {
    "Timeout",
    "Out of memory",
    "Fixpoint timeout",
    "Stack overflow",
    "Too many matches",
    "Internal matching error",
}

#: 파일 하나를 끝까지 분석하지 못하게 만드는 오류. 경로 없이 오면 어느 파일인지 모르는 오류로 다룬다.
FILE_LEVEL_ERRORS = (
    PARSE_ERRORS
    | RULE_LEVEL_ERRORS
    | {"Fatal error", "Timeout during interfile analysis", "OOM during interfile analysis"}
)

#: semgrep 의 --timeout-threshold 기본값. 한 파일에서 이만큼 시간 초과가 나면 나머지 규칙을 건너뛴다.
TIMEOUT_THRESHOLD = 3


#: 우리가 컴파일하는 규칙의 종류. 결과는 metadata 로, 오류는 규칙 id 로 가른다.
KIND_POLICY, KIND_REGION = "policy", "region"


class RuleInfo(NamedTuple):
    kind: str
    key: PredicateKey | None = None
    """정책 조건이면 그 조건. 시간 초과가 난 조건만 '모름'으로 둘 때 쓴다."""


def rule_table(config: dict) -> dict[str, RuleInfo]:
    """컴파일한 설정의 규칙 id → 종류(와 정책 조건). 결과를 가르는 것과 같은 metadata 표지로 정한다."""
    out: dict[str, RuleInfo] = {}
    for r in (config or {}).get("rules", []):
        md = r.get("metadata") or {}
        meta = md.get("policypack")
        if isinstance(md.get(REGION_MARKER), dict):
            info = RuleInfo(KIND_REGION)
        elif isinstance(meta, dict) and all(k in meta for k in ("policy", "rule", "group", "predicate")):
            info = RuleInfo(KIND_POLICY, PredicateKey(meta["policy"], meta["rule"], meta["group"], meta["predicate"]))
        else:
            info = RuleInfo(KIND_POLICY)
        out[str(r.get("id", ""))] = info
    return out


def canonical_rule_id(rule_id: str, known) -> str | None:
    """엔진이 돌려준 규칙 id 를 우리가 컴파일한 id 로 되돌린다.

    semgrep 은 id 앞에 설정 파일이 든 폴더의 경로(작업 폴더 기준)를 점으로 이어 붙인다
    (`var.folders.….T.kr.p.r.pred`, 임시 폴더가 작업 폴더와 같으면 접두사가 없다). 점 경계에서 끝이 맞는 id
    가운데 가장 긴 것을 고른다. 경로 조각을 문자열로 찾으면 임시 폴더 이름에 속는다. 한 id 가 다른 id 의
    점 경계 접미사면 이 되돌리기가 모호해지므로 컴파일러가 그런 id 조합을 거부한다(compile.check_rule_ids)."""
    best = None
    for cid in known:
        if (rule_id == cid or rule_id.endswith("." + cid)) and (best is None or len(cid) > len(best)):
            best = cid
    return best


def _canonical_ids_in(text: str, known) -> str:
    """문구 속 규칙 id 에서 엔진이 붙인 경로 접두사를 뗀다(`var.folders.….T.acme.p.r.c` → `acme.p.r.c`).
    규칙 오류를 읽는 사람은 임시 폴더 경로가 아니라 자기 팩의 정책·규칙·조건 이름을 봐야 한다."""
    return re.sub(r"[\w.\-]+", lambda m: canonical_rule_id(m.group(0), known) or m.group(0), text)


def _is_region_rule(rule_id: str) -> bool:
    # 함수 경계 규칙이 시간 초과로 끝나면 그 파일은 구역이 없는 것(파일 전체)이 될 뿐이다
    return rule_id.startswith("policypack-region") or ".policypack-region" in rule_id


def _type_label(err: dict[str, Any]) -> str:
    """오류 종류를 문자열 하나로 정규화한다.

    `type` 은 문자열일 수도 있고 `["PartialParsing", [스팬...]]` 같은 목록일 수도 있다.
    """
    t = err.get("type")
    if isinstance(t, list) and t:
        return str(t[0])
    return str(t) if t is not None else "unknown"


def _pos(d: dict[str, Any]) -> Pos:
    return Pos(line=int(d.get("line", 0)), col=int(d.get("col", 0)), offset=int(d.get("offset", 0)))


def _partial_spans(err: dict[str, Any]) -> list[tuple[Path, Span]]:
    """PartialParsing 오류에서 (파일, 스팬) 쌍을 꺼낸다."""
    t = err.get("type")
    if not (isinstance(t, list) and len(t) > 1 and isinstance(t[1], list)):
        return []
    out = []
    for s in t[1]:
        if not isinstance(s, dict) or "path" not in s:
            continue
        out.append((Path(s["path"]), Span(_pos(s.get("start", {})), _pos(s.get("end", {})))))
    return out


def parse_semgrep_json(data: dict[str, Any], table: dict[str, RuleInfo] | None = None) -> StaticResult:
    """`table` 은 `rule_table(config)`. 주면 오류의 규칙 id 를 컴파일한 id 로 되돌려 종류와 조건을 정확히 가른다.
    백엔드는 늘 준다. 없으면(시험에서 JSON 만 읽을 때) 규칙 id 문자열로 추정한다."""
    result = StaticResult()
    info_of: dict[str, RuleInfo | None] = {}

    for r in data.get("results", []):
        extra = r.get("extra") or {}
        metadata = extra.get("metadata") or {}

        if isinstance(metadata.get(REGION_MARKER), dict):
            # 함수 경계. 판정 구역을 정하는 데만 쓴다.
            span = Span(_pos(r.get("start", {})), _pos(r.get("end", {})))
            spans = result.regions.setdefault(Path(r["path"]), [])
            if span not in spans:
                spans.append(span)
            continue

        meta = metadata.get("policypack")
        if not isinstance(meta, dict):
            # 우리가 만든 규칙이라면 반드시 붙어 있다. 없으면 컴파일 쪽 버그다.
            result.rule_errors.append(
                f"매치에 policypack 메타데이터가 없습니다: check_id={r.get('check_id')!r}. "
                f"compile_static 이 metadata 를 붙이지 않았습니다."
            )
            continue
        result.matches.append(
            Match(
                key=PredicateKey(
                    policy=meta["policy"],
                    rule=meta["rule"],
                    group=meta["group"],
                    predicate=meta["predicate"],
                ),
                path=Path(r["path"]),
                span=Span(_pos(r.get("start", {})), _pos(r.get("end", {}))),
            )
        )

    partial: dict[Path, list[Span]] = defaultdict(list)
    for err in data.get("errors", []):
        label = _type_label(err)

        if label == "PartialParsing":
            spans = _partial_spans(err)
            for path, span in spans:
                partial[path].append(span)
            top = err.get("path")
            if top and Path(top) not in partial:
                partial[Path(top)] = []
            continue

        path_s = err.get("path")
        rule_id = err.get("rule_id")
        if path_s and rule_id and label in RULE_LEVEL_ERRORS:
            rid = str(rule_id)
            if table is not None:
                cid = canonical_rule_id(rid, table)
                # 모르는 id 는 None: 어느 조건인지 모르니 그 파일 전체를 끝나지 않은 것으로 본다
                info_of[cid or rid] = table.get(cid) if cid else None
                rid = cid or rid
            result.rule_timeouts.setdefault(Path(path_s), []).append(rid)
            continue
        if path_s:
            if table is not None and label not in PARSE_ERRORS:
                # 파싱은 됐는데 엔진이 이 파일을 끝내지 못했다. 정규식 사본의 '매치 없음'도 믿지 않는다
                result.incomplete.add(Path(path_s))
            else:
                # 파일 하나를 파싱하지 못했다. 사용자 코드 문제이지 규칙 문제가 아니다.
                result.hard_unparsed.add(Path(path_s))
            continue

        if label in FILE_LEVEL_ERRORS:
            # 파일 단위 오류인데 어느 파일인지 모른다. 규칙 오류는 아니지만 버리지도 않는다.
            # 백엔드가 그 실행의 대상 전체를 믿을 수 없는 것으로 둔다.
            msg = (err.get("long_msg") or err.get("message") or "").strip()
            result.unlocated_errors.append(f"[{label}] {msg[:200]}")
            continue

        msg = (err.get("long_msg") or err.get("message") or "").strip()
        if table is not None:
            msg = _canonical_ids_in(msg, table)
        result.rule_errors.append(f"[{label}] {msg[:400]}")

    for path, rules in result.rule_timeouts.items():
        if table is None:
            # 규칙 표가 없으면 추정한다: 정책 규칙의 시간 초과는 그 파일을 믿지 않는다
            pack_rules = [r for r in rules if not _is_region_rule(r)]
            if pack_rules or len(rules) >= TIMEOUT_THRESHOLD:
                result.hard_unparsed.add(path)
            continue
        infos = [info_of.get(r) for r in rules]
        if len(rules) >= TIMEOUT_THRESHOLD or any(i is None for i in infos):
            # 문턱에 닿으면 semgrep 이 나머지 규칙을 오류 없이 건너뛴다(실측). 모르는 규칙도 같이 다룬다
            result.incomplete.add(path)
        keys = [i.key for i in infos if i is not None and i.kind == KIND_POLICY and i.key is not None]
        if keys:
            result.predicate_timeouts.setdefault(path, []).extend(keys)

    result.partial_unparsed = dict(partial)
    return result
