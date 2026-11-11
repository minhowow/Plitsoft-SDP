"""기계가 읽는 출력.

SARIF 는 코드 스캐닝 플랫폼에 맞춘 형식이라 우리 고유의 값(세 값 판정, 판정 경로,
AI 해제 기록)을 properties 에 밀어 넣어야 한다. 이쪽은 그런 제약이 없어서
해석기가 실제로 아는 것을 그대로 낸다.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from policypack import __version__
from policypack.evaluate.engine import EvalResult
from policypack.index.roles import SERVICE, file_role
from policypack.report.fingerprint import VERSION as FP_VERSION
from policypack.report.fingerprint import fingerprints
from policypack.report.paths import rel

SCHEMA_VERSION = 1
"""보고서 JSON(scan·test)의 판. 키를 더할 때는 올리지 않는다. 있던 키가 없어지거나 뜻이 바뀌면 올린다."""


def build(result: EvalResult, root: Path | None = None, pack_digest: str = "", meta: dict | None = None) -> dict:
    fps = fingerprints(result.findings, pack_digest, root)
    roles = [file_role(_rel(f.file, root), f.file) for f in result.findings]
    service = sum(r in SERVICE for r in roles)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "policypack", "version": __version__},
        "run": {
            "judge": result.judge_id or None,
            "pack_digest": pack_digest,
            # findings[].fingerprint 를 만드는 방식의 이름. 방식을 바꾸면 이 값이 바뀐다
            "fingerprint_version": FP_VERSION,
            "questions_asked": result.questions_asked,
            "ai_answered": result.ai_answered,
            "questions_sent": result.questions_sent,
            # 판정자가 연달아 시간 안에 답하지 않아 보내지 않은 서로 다른 질문 수(questions_sent 와 같은 기준)
            "questions_skipped": result.questions_skipped,
            # AI 에게 물어야 했는데 답을 받지 못한 판정 단위 수(판정자 없음 포함)
            "ai_pending": result.ai_pending,
            # AI 의 '예'로 풀린 경고와, 적용 질문의 '아니오'로 빠진 판정. 사람이 검토할 수 있게 낸다
            "ai_cleared": [cleared_record(c, lambda p: _rel(p, root)) for c in result.ai_cleared],
            "ai_dismissed": [{**d, "file": _rel(d["file"], root)} for d in result.ai_dismissed],
            # 강한 정적 대안으로 풀린 단위와 그 대안이 맞은 줄 번호. units = findings + ai_cleared + static_cleared
            "static_cleared": [cleared_record(c, lambda p: _rel(p, root)) for c in result.static_cleared],
            "engine": _engine(result.engine),
            "static_seconds": round(result.static_seconds, 3),
            "ai_seconds": round(result.ai_seconds, 3),
            "units": len(result.units),
            # findings[].file 과 맞춰 볼 수 있게 같은 기준으로 낸다
            "unparsed": [_rel(p, root) for p in result.unparsed],
            "skipped": [_rel(p, root) for p in result.skipped],
            # 엔진이 정책 조건을 끝까지 돌리지 못했거나 함수 경계를 얻지 못한 파일(파싱 실패와 다르다)과, 어느
            # 파일인지 모르는 엔진 오류
            "incomplete": [_rel(p, root) for p in result.incomplete],
            "engine_errors": list(result.engine_errors),
            "coverage_complete": result.coverage_complete,
            # 발견을 파일 역할로 나눈 수. 서비스 코드는 server·screen·other, 그 밖은 test(시험·픽스처·목업·스토리)와
            # config. 역할은 경로와 내용의 모양으로 고른 힌트라 판정과 종료 코드는 이것을 보지 않는다
            "finding_counts": {
                "total": len(roles),
                "service": service,
                "non_service": len(roles) - service,
                "by_role": dict(sorted(Counter(r.value for r in roles).items())),
            },
            # 에이전트 검토 단계를 돌렸을 때만 싣는다(--agent). 판정기, 후보 단위, 인용 관문 결과, 사용량
            **({"judge_usage": result.judge_usage} if result.judge_usage else {}),
            # 판정자에게 보내기 전에 가린 비밀값 수(종류별). 가린 것이 있을 때만
            **({"judge_masked": result.judge_masked} if result.judge_masked else {}),
            **({"agent": result.agent} if result.agent is not None else {}),
            **(meta or {}),
        },
        "findings": [
            {
                "policy": f.policy,
                "rule": f.rule,
                "outcome": f.outcome.value,
                "file": _rel(f.file, root),
                "line": f.line,
                "role": role.value,
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
                **({"agent": f.agent} if f.agent is not None else {}),
            }
            for f, fp, role in zip(result.findings, fps, roles, strict=True)
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
    """해제 기록 하나(AI·정적). 판정 파일을 다른 출력과 같은 기준(상대 경로)으로 낸다."""
    return {**c, "file": path(c["file"])}
