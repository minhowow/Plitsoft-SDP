"""adjudicate.py 시험. 모델을 부르지 않는다."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def write(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def row(file, label, labeler, scope=None, error=None):
    return {
        "file": file,
        "policy": "p",
        "label": label,
        "label_ko": label,
        "labeler": labeler,
        "reason": "r",
        "citations": [],
        "scope": scope,
        "source": "screened",
        "error": error,
    }


def run(*args):
    return subprocess.run(
        [sys.executable, "-I", str(HERE / "adjudicate.py"), *map(str, args)], capture_output=True, text=True, check=True
    ).stdout


def test_merge_then_adjudicate(tmp_path):
    a = write(
        tmp_path / "a.jsonl",
        [
            row("r/1.ts", "needs-review", "A"),
            row("r/2.ts", "compliant", "A"),
            row("r/3.ts", "not-applicable", "A", scope="시험·스토리 파일"),
        ],
    )
    b = write(
        tmp_path / "b.jsonl",
        [
            row("r/1.ts", "needs-review", "B"),
            row("r/2.ts", "needs-review", "B"),
            row("r/3.ts", "not-applicable", "B"),
            row("r/4.ts", "compliant", "B", error="x"),
        ],
    )
    out = run("merge", "--a", a, "--b", b, "--out", tmp_path / "l.json", "--disputes", tmp_path / "d.json")
    assert "agreed': 2" in out and "pending': 1" in out and "범위 표시가 갈림 1" in out
    labels = {r["file"]: r for r in json.loads((tmp_path / "l.json").read_text())}
    assert labels["r/2.ts"]["label"] == "unsure" and labels["r/3.ts"]["scope"] == "시험·스토리 파일"
    assert "r/4.ts" not in labels  # 오류가 난 답은 빼고
    disputes = json.loads((tmp_path / "d.json").read_text())
    assert [d["file"] for d in disputes] == ["r/2.ts"] and len(disputes[0]["answers"]) == 2
    adj = write(tmp_path / "adj.jsonl", [row("r/2.ts", "compliant", "adj")])
    run("merge", "--a", a, "--b", b, "--adj", adj, "--out", tmp_path / "l2.json")
    labels = {r["file"]: r for r in json.loads((tmp_path / "l2.json").read_text())}
    assert labels["r/2.ts"]["label"] == "compliant" and labels["r/2.ts"]["how"] == "adjudicated"
