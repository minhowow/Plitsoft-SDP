"""정책 팩의 정적 조건을 Semgrep 설정 하나로 모은다.

모든 정책의 모든 정적 조건이 규칙 하나짜리 목록으로 합쳐지고, 정책 조건은 semgrep **한 번**으로
돈다(함수 경계 규칙은 백엔드가 필요한 파일에만 따로 돌린다). Semgrep 엔진은 고치지 않는다. 해석기가
부품으로 쓸 뿐이다.

## 되짚기를 metadata 로 한다

semgrep 은 설정 파일 경로를 check_id 앞에 붙여 돌려준다. 그래서 매치를 조건으로 되짚을 때 id 의
부분 문자열에 기대지 않고 규칙 `metadata` 를 쓴다. semgrep 은 metadata 의 임의 중첩 키를 JSON
출력에 그대로 싣는다(한국어 키도 그대로).

## 정규식 조건의 generic 사본

파일 전체가 파싱되지 않으면 언어가 붙은 정규식 규칙도 매치되지 않는다(실측).
"정규식은 파싱과 무관하다"는 성질을 실제로 얻으려면 `languages: [generic]` 사본이
필요하다. 사본에는 언어별 확장자 필터를 붙여서, 정규식이 README 같은 데까지
번지지 않게 한다.
"""

from __future__ import annotations

import re
from typing import Any

from policypack.errors import PackError
from policypack.model import Policy, PolicyPack, Rule, Scope

#: 언어 → 파일 확장자. generic 사본의 범위를 제한하는 데 쓴다.
LANGUAGE_GLOBS: dict[str, list[str]] = {
    "javascript": ["*.js", "*.jsx", "*.mjs", "*.cjs"],
    # .mts·.cts 는 넣지 않는다. 고정한 Semgrep 1.176.1 이 TypeScript 로 읽지 않는다(discover.ENGINE_UNREADABLE)
    "typescript": ["*.ts", "*.tsx"],
    "python": ["*.py", "*.pyi"],
    "go": ["*.go"],
    "java": ["*.java"],
    "ruby": ["*.rb"],
    "php": ["*.php"],
}

_SAFE = re.compile(r"[^A-Za-z0-9._-]")

GROUP_APPLIES = "applies-when"
GROUP_COMPLIANT = "compliant-if-any"


#: scope: anchor 의 판정 구역 = 앵커를 감싸는 가장 바깥 함수. 언어별 함수 패턴.
#: 실측(1.176): `function $F(...) {...}` 는 선언·클래스 메서드·getter 를,
#: `function (...) {...}` 는 익명 함수식과 화살표 함수(블록·식 본문)를 잡는다.
REGION_PATTERNS: dict[str, list[str]] = {
    "javascript": ["function $F(...) { ... }", "function (...) { ... }"],
    "typescript": ["function $F(...) { ... }", "function (...) { ... }"],
}

#: 함수 경계 규칙 매치를 가려내는 metadata 키
REGION_MARKER = "policypack_region"

#: 함수 단위 규칙의 적용 조건에 붙는 metadata 키. 값은 "on"(anchor-on 조건) 또는 "with"(나머지 적용 조건)
ANCHOR_ROLE = "anchor"


def region_rules(languages: set[str]) -> list[dict[str, Any]]:
    """함수 경계 규칙. 패턴 목록이 같은 언어는 규칙 하나로 묶는다.

    언어마다 규칙을 따로 두면 semgrep 이 javascript 규칙을 TypeScript 파일에도 돌려 함수마다 매치가 둘 나오고
    그만큼 느려진다(실측: 함수 4,140개에 매치 7,620건)."""
    by_patterns: dict[tuple[str, ...], list[str]] = {}
    for lang in sorted(languages):
        pats = REGION_PATTERNS.get(lang)
        if pats:
            by_patterns.setdefault(tuple(pats), []).append(lang)
    return [
        {
            "id": "policypack-region." + "-".join(langs),
            "languages": langs,
            "severity": "INFO",
            "message": "region",
            "metadata": {REGION_MARKER: {"lang": "-".join(langs)}},
            "pattern-either": [{"pattern": p} for p in pats],
        }
        for pats, langs in by_patterns.items()
    ]


def _rule_id(policy: Policy, rule: Rule, pred_id: str, *, generic: bool) -> str:
    base = f"{policy.id}.{rule.id}.{pred_id}"
    return _SAFE.sub("_", base) + (".generic" if generic else "")


def _globs_for(languages: list[str]) -> list[str]:
    out: list[str] = []
    for lang in languages:
        out.extend(LANGUAGE_GLOBS.get(lang, []))
    return sorted(set(out))


def compile_static(pack: PolicyPack) -> dict[str, Any]:
    """정책 팩 → semgrep 설정 하나.

    되짚기에 필요한 것은 전부 규칙 metadata 에 실려 나가므로 별도의 index 를
    돌려주지 않는다.
    """
    rules: list[dict[str, Any]] = []

    for policy, rule in pack.iter_rules():
        languages = pack.languages_for(rule)
        groups = ((GROUP_APPLIES, rule.applies_when), (GROUP_COMPLIANT, rule.compliant_if_any))
        for group, preds in groups:
            for pred in preds:
                if pred.static is None:
                    continue
                meta = {"policy": policy.id, "rule": rule.id, "group": group, "predicate": pred.id}
                if rule.scope is Scope.ANCHOR and group == GROUP_APPLIES:
                    # 함수 경계가 필요한 파일을 고르는 데 쓴다(백엔드). 판정 위치 조건은 "on", 나머지 적용 조건은 "with"
                    meta[ANCHOR_ROLE] = "on" if pred.id == rule.anchor_on else "with"
                rules.append(
                    {
                        "id": _rule_id(policy, rule, pred.id, generic=False),
                        "languages": languages,
                        "severity": "INFO",
                        "message": pred.id,
                        "metadata": {"policypack": meta},
                        **pred.static,
                    }
                )
                if pred.parse_independent:
                    globs = _globs_for(languages)
                    generic = {
                        "id": _rule_id(policy, rule, pred.id, generic=True),
                        "languages": ["generic"],
                        "severity": "INFO",
                        "message": pred.id,
                        "metadata": {"policypack": {**meta, "generic": True}},
                        **pred.static,
                    }
                    if globs:
                        generic["paths"] = {"include": globs}
                    rules.append(generic)

    # 함수 경계 규칙은 scope: anchor 규칙이 있을 때만 붙인다. 없으면 설정에 아무것도 더하지 않는다
    anchor_langs = {lang for _, r in pack.iter_rules() if r.scope is Scope.ANCHOR for lang in pack.languages_for(r)}
    if anchor_langs:
        rules += region_rules(anchor_langs)

    check_rule_ids(rules)
    return {"rules": rules}


def check_rule_ids(rules: list[dict[str, Any]]) -> None:
    """규칙 id 가 겹치거나, 한 id 가 다른 id 의 점 경계 접미사면 거부한다.

    semgrep 은 오류의 규칙 id 앞에 설정 폴더 경로를 붙여 돌려준다. 파서는 가장 긴 점 경계 접미사로 우리
    id 를 되찾는데, 접미사 관계인 id 가 둘 있으면 폴더 이름에 따라 엉뚱한 조건으로 읽는다. 정책 id 에 점이
    들어가므로(kr.pipa.22-2) 정책 `pipa` 의 `pipa.r.c` 와 정책 `kr.pipa` 의 `kr.pipa.r.c` 가 그런 짝이다."""
    ids = [str(r.get("id", "")) for r in rules]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise PackError(f"semgrep 규칙 id 가 겹칩니다: {', '.join(dup[:5])}")
    by_len = sorted(set(ids), key=len)
    clash = [(a, b) for i, a in enumerate(by_len) for b in by_len[i + 1 :] if b.endswith("." + a)]
    if clash:
        a, b = clash[0]
        raise PackError(
            f"semgrep 규칙 id '{b}' 가 '{a}' 로 끝납니다. 엔진이 돌려준 id 를 어느 조건으로 되돌릴지 모호해집니다. "
            f"정책·규칙·조건 id 를 바꾸세요({len(clash)}건)."
        )
