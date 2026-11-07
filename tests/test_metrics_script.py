"""scripts/metrics.py: 정답 없이 세는 지표. 모델을 부르지 않는다."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("metrics", REPO / "scripts" / "metrics.py")
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)


def _q(failure=None, read=(), masked=None):
    return {"failure": failure, "sent": {"read": list(read), "masked": masked or {}}}


def test_counts_every_stage_and_prices_each_judge(tmp_path):
    doc = {
        "findings": [{"outcome": "needs-review"}, {"outcome": "needs-review-uncertain"}],
        "run": {
            "files": 3,
            "static_seconds": 1.5,
            "agent": {
                "judge": "agent:anthropic:claude-haiku-5-5",
                "mode": "combined",
                "actions": {"cleared": 1, "kept-no-answer": 1},
                "citations": 4,
                "citations_rejected": 1,
                "model_calls": 2,
                "usage": {"input_tokens": 1_000_000},
                "questions": [_q(read=["a.ts", "b.ts"], masked={"api-key": 1}), _q(failure="transport: x")],
                "discover": {
                    "judge": "agent:anthropic:claude-haiku-5-5",
                    "actions": {"warned": 2},
                    "citations": 2,
                    "citations_rejected": 0,
                    "model_calls": 1,
                    "usage": {"output_tokens": 1_000_000},
                    "questions": [_q(read=["a.ts"])],
                },
                "recheck": {
                    "judge": "agent:anthropic:claude-sonnet-5-5",
                    "actions": {"confirmed": 1},
                    "model_calls": 1,
                    "usage": {"input_tokens": 1_000_000},
                    "questions": [_q(masked={"api-key": 1, "jwt": 1})],
                },
                "questions_skipped": 3,
            },
        },
    }
    p = tmp_path / "o__r.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    row = metrics.one(p)
    assert (row["needs_review"], row["uncertain"], row["cleared"], row["confirmed"], row["warned"]) == (1, 1, 1, 1, 2)
    assert (row["citations"], row["citations_rejected"], row["unanswered"], row["skipped"]) == (6, 1, 1, 3)
    assert row["files_read"] == 2 and row["masked"] == {"api-key": 2, "jwt": 1} and row["model_calls"] == 4
    assert row["usd"] == 1.0 + 5.0 + 3.0  # haiku 입력 · haiku 출력 · sonnet 입력, 100만 토큰씩
    assert "1/6 (17%)" in metrics.table([row])


def test_a_scan_without_agent_has_only_static_columns(tmp_path):
    p = tmp_path / "plain.json"
    p.write_text(json.dumps({"findings": [], "run": {"files": 1, "static_seconds": 0.2}}), encoding="utf-8")
    out = metrics.table([metrics.one(p)])
    assert "인용 거절" not in out and "| plain | 1 | 0 | 0 | 0.2 |" in out
