"""기계가 읽는 출력.

SARIF 는 코드 스캐닝 플랫폼에 맞춘 형식이라 우리 고유의 값(세 값 판정, 판정 경로,
AI 해제 기록)을 properties 에 밀어 넣어야 한다. 이쪽은 그런 제약이 없어서
해석기가 실제로 아는 것을 그대로 낸다.
"""

from __future__ import annotations

import json
from pathlib import Path

from policypack import __version__
from policypack.evaluate.engine import EvalResult
from policypack.report.fingerprint import fingerprints
from policypack.report.paths import rel


def build(result: EvalResult, root: Path | None = None, pack_digest: str = "", meta: dict | None = None) -> dict:
    fps = fingerprints(result.findings, pack_digest, root)
    return {
        "tool": {"name": "policypack", "version": __version__},
        "run": {
            "judge": result.judge_id or None,
            "pack_digest": pack_digest,
            "questions_asked": result.questions_asked,
            "ai_answered": result.ai_answered,
            "questions_sent": result.questions_sent,
            # AI 에게 물어야 했는데 답을 받지 못한 판정 단위 수(판정자 없음 포함)
            "ai_pending": result.ai_pending,
            # AI 의 '예'로 풀린 경고와, 적용 질문의 '아니오'로 빠진 판정. 사람이 검토할 수 있게 낸다
            "ai_cleared": [cleared_record(c, lambda p: _rel(p, root)) for c in result.ai_cleared],
            "ai_dismissed": [{**d, "file": _rel(d["file"], root)} for d in result.ai_dismissed],
            "engine": _engine(result.engine),
            "static_seconds": round(result.static_seconds, 3),
            "ai_seconds": round(result.ai_seconds, 3),
            "units": len(result.units),
            # findings[].file 과 맞춰 볼 수 있게 같은 기준으로 낸다
            "unparsed": [_rel(p, root) for p in result.unparsed],
            "skipped": [_rel(p, root) for p in result.skipped],
            # 엔진이 정책 조건을 끝까지 돌리지 못한 파일(파싱 실패와 다르다)과, 어느 파일인지 모르는 엔진 오류
            "incomplete": [_rel(p, root) for p in result.incomplete],
            "engine_errors": list(result.engine_errors),
            "coverage_complete": result.coverage_complete,
            **(meta or {}),
        },
        "findings": [
            {
                "policy": f.policy,
                "rule": f.rule,
                "outcome": f.outcome.value,
                "file": _rel(f.file, root),
                "line": f.line,
                "case": f.case,
                "category": f.category,
                "title": f.title,
                "law": f.law,
                "ask_developer": f.ask_developer,
                "untested_reasons": [r.value for r in f.untested_reasons],
                "ai_pending": f.ai_pending,
                "fingerprint": fp,
                "scope": f.scope,
                "region": {"start_line": f.region[0], "end_line": f.region[1]} if f.region else None,
                "top_level": f.top_level,
                "anchor_lines": f.anchor_lines,
                "unsatisfied_alternatives": f.alternatives,
                "decision_path": f.trace,
            }
            for f, fp in zip(result.findings, fps, strict=True)
        ],
    }


def _engine(label: str) -> dict | None:
    """ "semgrep 1.176.1" → {"name": "semgrep", "version": "1.176.1"}. 엔진을 돌리지 않았으면 None."""
    if not label:
        return None
    name, _, version = label.partition(" ")
    return {"name": name, "version": version or None}


def _rel(path_str: str, root: Path | None) -> str:
    return rel(path_str, root)


def dumps(*args, **kwargs) -> str:
    return json.dumps(build(*args, **kwargs), ensure_ascii=False, indent=2)


def cleared_record(c: dict, path) -> dict:
    """AI 해제 기록 하나. 판정 파일을 다른 출력과 같은 기준(상대 경로)으로 낸다."""
    return {**c, "file": path(c["file"])}
