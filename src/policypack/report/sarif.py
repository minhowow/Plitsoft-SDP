"""SARIF 2.1.0 출력.

우리가 직접 쓰므로 semgrep 이 무엇을 가리든 상관없다. 중요한 것은 **근거 조문이
어디로 가느냐**다.

| SARIF 자리 | 우리가 넣는 것 |
|---|---|
| `rules[].help.markdown` | 조문 원문 + 시행일 + 법제처 링크 + 재검토 기한 |
| `rules[].helpUri` | 법제처 링크 |
| `rules[].properties.tags` | `law:...`, `effective-from:...`, `category:...` |
| `results[].level` | 검토 필요 → warning · 불확실 → note |
| `results[].partialFingerprints` | 줄 번호를 뺀 안정 해시 |
| `results[].properties` | outcome, 판정 경로, 안 맞은 대안, 다 판정하지 못한 이유, AI 확인 필요 |

GitHub·GitLab 코드 스캐닝이 `help.markdown` 을 그대로 보여 주므로, 개발자가
도구를 떠나지 않고 조문을 읽을 수 있다.
"""

from __future__ import annotations

import json
from pathlib import Path

from policypack import __version__
from policypack.discover import SKIPPED_REASONS
from policypack.evaluate.engine import EvalResult
from policypack.model import LegalRef, Policy, PolicyPack
from policypack.report.fingerprint import VERSION as FP_VERSION
from policypack.report.fingerprint import fingerprints
from policypack.report.json_out import cleared_record
from policypack.report.outcome import Finding, Outcome
from policypack.report.paths import rel

SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
INFO_URI = "https://github.com/policypack/policypack"

LEVEL = {
    Outcome.NEEDS_REVIEW: "warning",
    Outcome.NEEDS_REVIEW_UNCERTAIN: "note",
}


def _legal_markdown(policy: Policy, base: Path) -> str:
    """조문 원문을 그대로 싣는다. 해시로 고정된 그 파일이다."""
    parts: list[str] = []
    if policy.rationale and policy.rationale.motivation:
        parts.append(policy.rationale.motivation.strip())

    for ref in policy.legal.violated_when_failed if policy.legal else []:
        head = f"### {ref.statute} {ref.article}" + (f" {ref.clause}" if ref.clause else "")
        parts.append(head)
        meta = []
        if ref.effective_from:
            meta.append(f"시행 {ref.effective_from}")
        if ref.law_id:
            meta.append(f"법령ID {ref.law_id}")
        if ref.text_retrieved:
            meta.append(f"원문 확인 {ref.text_retrieved}")
        if meta:
            parts.append(" · ".join(meta))
        text = _statute_text(ref, base)
        if text:
            parts.append("```\n" + text.strip() + "\n```")
        if ref.url:
            parts.append(f"[법제처 원문]({ref.url})")

    if policy.review:
        parts.append(f"재검토 기한 {policy.review.review_by}")
    parts.append("이 도구는 법률 자문이 아닙니다. 검토가 필요한 지점을 고를 뿐입니다.")
    return "\n\n".join(parts)


def _statute_text(ref: LegalRef, base: Path) -> str:
    if not ref.text_file:
        return ""
    try:
        return (base / ref.text_file).read_text(encoding="utf-8")
    except OSError:
        return ""


def _tags(policy: Policy) -> list[str]:
    tags = ["policypack", f"category:{policy.category}"]
    for ref in policy.legal.violated_when_failed if policy.legal else []:
        tags.append(f"law:{ref.statute}-{ref.article}")
        if ref.effective_from:
            tags.append(f"effective-from:{ref.effective_from}")
    return tags


def _uri(path_str: str, root: Path | None) -> str:
    return rel(path_str, root)


def build(
    result: EvalResult,
    pack: PolicyPack,
    pack_base: Path,
    root: Path | None = None,
    pack_digest: str = "",
) -> dict:
    policies = {p.id: p for p in pack.policies}

    # 실제로 판정을 낸 규칙만 rules[] 에 싣는다.
    # ruleIndex 는 rules[] 에 실제로 넣은 순서로 매긴다. 틀린 ruleIndex 는 없는 것보다 나쁘다.
    rules: list[dict] = []
    index: dict[str, int] = {}
    for f in result.findings:
        if f.ref in index:
            continue
        index[f.ref] = len(rules)
        rules.append(_policy_rule(f.ref, f.rule, policies[f.policy], pack_base))

    fps = fingerprints(result.findings, pack_digest, root)
    results = [_result(f, index[f.ref], root, fp) for f, fp in zip(result.findings, fps, strict=True)]

    return {
        "$schema": SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "policypack",
                        "version": __version__,
                        "informationUri": INFO_URI,
                        "rules": rules,
                    },
                    # 정적 조건을 돌린 엔진. 엔진이나 판이 바뀌면 결과가 달라질 수 있다
                    **({"extensions": [_engine_component(result.engine)]} if result.engine else {}),
                },
                "invocations": [
                    {
                        # 도구는 제대로 끝났다. 다 보지 못한 것은 알림과 coverageComplete 로 말한다.
                        "executionSuccessful": True,
                        "toolExecutionNotifications": _gaps(result, root),
                        "properties": {
                            "judge": result.judge_id or "none",
                            "aiQuestions": result.questions_asked,
                            "aiAnswered": result.ai_answered,
                            "aiPending": result.ai_pending,
                            # AI 가 푼 경고와 적용 질문으로 뺀 판정. 결과(results)로 내지 않는다 — 경고가 아니다
                            "aiCleared": [cleared_record(c, lambda p: _uri(p, root)) for c in result.ai_cleared],
                            "aiDismissed": [{**d, "file": _uri(d["file"], root)} for d in result.ai_dismissed],
                            "packDigest": pack_digest,
                            "coverageComplete": result.coverage_complete,
                        },
                    }
                ],
                "results": results,
            }
        ],
    }


def _engine_component(label: str) -> dict:
    name, _, version = label.partition(" ")
    return {"name": name, **({"version": version} if version else {})}


def _policy_rule(ref: str, rule_id: str, policy: Policy, pack_base: Path) -> dict:
    return {
        "id": ref,
        "name": rule_id.replace("-", " ").title().replace(" ", ""),
        "shortDescription": {"text": policy.title},
        "fullDescription": {"text": (policy.rationale.implementation if policy.rationale else policy.title)},
        "help": {
            "text": policy.ask_developer or policy.title,
            "markdown": _legal_markdown(policy, pack_base),
        },
        "helpUri": _help_uri(policy),
        "defaultConfiguration": {"level": "warning"},
        "properties": {"tags": _tags(policy), "precision": "medium"},
    }


def _gaps(result: EvalResult, root: Path | None) -> list[dict]:
    """다 보지 못한 파일. 경고가 없다는 것이 "문제 없음"이 아니라 "못 봤음"일 수 있다."""

    def note(kind: str, path: str, text: str) -> dict:
        return {
            "level": "warning",
            "descriptor": {"id": f"policypack/{kind}"},
            "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": _uri(path, root)}}}],
        }

    unparsed = "파싱하지 못했습니다. 이 파일의 구문 조건은 확인되지 않았습니다."
    out = [note("unparsed", p, unparsed) for p in result.unparsed]
    out += [note("skipped", p, f"검사하지 않았습니다({SKIPPED_REASONS}).") for p in result.skipped]
    incomplete = "엔진이 이 파일에서 정책 조건을 끝내지 못했습니다(시간 초과 등). 파일 문법 문제가 아닙니다."
    out += [note("engine-incomplete", p, incomplete) for p in result.incomplete]
    if result.ai_pending:
        from policypack.report.text import pending_note

        out.append(
            {
                "level": "note",
                "descriptor": {"id": "policypack/ai-pending"},
                "message": {"text": pending_note(result) + "."},
            }
        )
    # 어느 파일인지 모르는 엔진 오류. 위치 없이 알린다
    out += [
        {"level": "warning", "descriptor": {"id": "policypack/engine-error"}, "message": {"text": text}}
        for text in result.engine_errors
    ]
    return out


def _help_uri(policy: Policy) -> str:
    if policy.legal and policy.legal.violated_when_failed:
        return policy.legal.violated_when_failed[0].url or INFO_URI
    return INFO_URI


def _result(f: Finding, rule_index: int, root: Path | None, fp: str) -> dict:
    message = f.alternatives[0]["message"] if f.alternatives else f.title
    if f.ask_developer:
        message = f"{message} — {f.ask_developer}"

    region = {"startLine": f.line} if f.line else {"startLine": 1}
    location: dict = {"artifactLocation": {"uri": _uri(f.file, root)}, "region": region}
    if f.region and f.line and f.region[0] <= f.line <= f.region[1] and f.region[0] < f.region[1]:
        # 판정 구역. 코드 스캐닝 UI 가 경고 둘레로 보여 준다. SARIF 는 contextRegion 이 region 을
        # 넘어서야 한다고 본다 — 한 줄짜리 함수면 region 과 같아서 싣지 않는다
        location["contextRegion"] = {"startLine": f.region[0], "endLine": f.region[1]}
    out = {
        "ruleId": f.ref,
        "ruleIndex": rule_index,
        "level": LEVEL.get(f.outcome, "note"),
        "message": {"text": message},
        "locations": [{"physicalLocation": location}],
        "partialFingerprints": {FP_VERSION: fp},
        "properties": {
            "outcome": f.outcome.value,
            "law": f.law,
            "untestedReasons": [r.value for r in f.untested_reasons],
            "aiPending": f.ai_pending,
            "decisionPath": f.trace,
            "unsatisfiedAlternatives": f.alternatives,
            "scope": f.scope,
        },
    }
    related = [
        {
            "id": i,
            "physicalLocation": {"artifactLocation": {"uri": _uri(f.file, root)}, "region": {"startLine": line}},
            "message": {"text": "같은 판정 구역의 다른 위치"},
        }
        for i, line in enumerate(f.anchor_lines[1:], start=1)
    ]
    if related:
        out["relatedLocations"] = related
    return out


def dumps(*args, **kwargs) -> str:
    return json.dumps(build(*args, **kwargs), ensure_ascii=False, indent=2)
