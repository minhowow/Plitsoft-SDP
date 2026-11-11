"""schemas/report-1.json 이 scan 의 JSON 보고서를 그대로 설명하는가. 웹이 이 스키마로 결과를 읽는다(웹 쪽 요청 R2).

스키마는 손으로 쓴다(보고서에는 pydantic 모델이 없다). 그래서 실제로 나오는 보고서를 여러 경우로 만들어 검사한다:
판정자 없음, 판정자가 푼 것·뺀 것, 에이전트 세 방식, 서비스에 닿지 못한 에이전트. 키를 더하면 이 시험이 실패하므로
스키마도 함께 고친다.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from policypack.evaluate.engine import Target, evaluate
from policypack.judge.fake import FakeJudge
from policypack.pack.loader import load_pack
from policypack.report import json_out
from policypack.static.backend import StaticResult
from policypack.static.compile import compile_static
from policypack.static.semgrep_cli import SemgrepBackend

jsonschema = pytest.importorskip("jsonschema")

REPO = Path(__file__).resolve().parents[1]
KR = REPO / "policies" / "kr-core"
FIX = KR / "tests"
SCHEMA = json.loads((REPO / "schemas" / "report-1.json").read_text(encoding="utf-8"))


def check(doc: dict) -> None:
    errors = sorted(jsonschema.Draft202012Validator(SCHEMA).iter_errors(doc), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message[:200]}" for e in errors[:5])


def test_the_schema_is_valid_and_versioned():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    assert SCHEMA["properties"]["schema_version"] == {"const": json_out.SCHEMA_VERSION}


@pytest.mark.parametrize("answer", [None, "예", "아니오"])
def test_judged_reports_match(answer):
    pack = load_pack(KR)
    names = ["network-act-50-3/violating.ts", "network-act-50-3/ai-night-guard.ts", "pipa-22-2/violating.ts"]
    names += ["pipa-22-2/under14-branch.ts", "pipa-22-2/guardian-call.ts", "pipa-28-8/redact-before-send.ts"]
    targets = [FIX / n for n in names]
    static = SemgrepBackend().run(compile_static(pack), targets)
    judge = FakeJudge(answer, echo_first_line=True) if answer else None
    res = evaluate(pack, [Target(path=p, lang="typescript") for p in targets], static, judge=judge)
    doc = json_out.build(res, root=FIX, pack_digest="d", meta={"files": len(targets)})
    assert answer != "예" or doc["run"]["ai_cleared"]
    check(doc)


def test_a_dismissed_unit_matches():
    pack = load_pack(KR)
    path = (FIX / "pipa-22-2" / "violating.ts").resolve()
    res = evaluate(
        pack, [Target(path=path, lang="typescript")], StaticResult(incomplete={path}), judge=FakeJudge("아니오")
    )
    doc = json_out.build(res, root=FIX)
    assert doc["run"]["ai_dismissed"]
    check(doc)


def _reply(app: Path):
    """진입 파일마다 충족·미충족·모름을 돌려 가며, 그 파일의 둘째 줄을 틀린 줄 번호로 인용한다."""

    def send(body):
        text = body["messages"][0]["content"][0]["text"]
        entries = [ln.split("`")[1] for ln in text.splitlines() if ln.strip().startswith("- `")] or ["signup.ts"]
        res = []
        for i, e in enumerate(entries[:3] + ["ghost.ts"]):
            code = (app / e).read_text().splitlines() if (app / e).is_file() else ["x"]
            res.append(
                {
                    "entry": e,
                    "verdict": ["미충족", "충족", "모름"][i % 3],
                    "line": 2,
                    "reason": "r",
                    "citations": [{"file": e, "line": 99, "text": code[min(1, len(code) - 1)]}],
                }
            )
        doc = json.dumps({"results": res}, ensure_ascii=False)
        return {"content": [{"type": "text", "text": doc}], "usage": {"input_tokens": 10, "output_tokens": 3}}

    return send


@pytest.mark.parametrize("mode", ["review", "combined", "independent", "offline"])
def test_agent_reports_match(tmp_path, monkeypatch, capsys, mode):
    import policypack.judge.agent as agent_mod
    from policypack.cli import main
    from policypack.judge.agent import AgentJudge
    from policypack.judge.http import Unavailable

    app = tmp_path / "app"
    app.mkdir()
    for src, name in [
        ("pipa-22-2/violating.ts", "signup.ts"),
        ("pipa-22-2/guardian-call.ts", "guard.ts"),
        ("pipa-28-8/openai-profile-summary.ts", "summary.ts"),
        ("network-act-50-3/violating.ts", "ads.ts"),
    ]:
        shutil.copy(FIX / src, app / name)

    def down(body):
        raise Unavailable("연결 실패")

    send = down if mode == "offline" else _reply(app)
    monkeypatch.setattr(agent_mod, "build", lambda spec, budget=20, env=None: AgentJudge("m", send, budget=budget))
    args = ["scan", str(app), "--output-format", "json", "--exit-zero", "--agent", "anthropic:m"]
    if mode == "combined":
        args += ["--agent-mode", "combined", "--agent-recheck", "anthropic:m2"]
    elif mode != "offline":
        args += ["--agent-mode", mode]
    main(args)
    doc = json.loads(capsys.readouterr().out)
    agent = doc["run"]["agent"]
    if mode == "offline":
        assert agent["questions_skipped"]
    else:
        assert any(c.get("line_model") == 99 for r in agent["records"] for c in r["citations"])
    check(doc)


def test_findings_carry_the_file_role(tmp_path, monkeypatch, capsys):
    """시험 파일의 발견도 그대로 내되 역할을 싣고, 글 출력은 그 발견을 뒤에 따로 묶는다(웹 시연, 11/11)."""
    from policypack.cli import main

    monkeypatch.chdir(tmp_path)  # git 저장소가 아니면 실행 위치가 검사 루트다
    for name in ("src/signup.ts", "tests/signup.test.ts"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIX / "pipa-22-2" / "violating.ts", tmp_path / name)
    assert main(["scan", str(tmp_path), "--output-format", "json"]) == 1
    doc = json.loads(capsys.readouterr().out)
    check(doc)
    assert {f["file"]: f["role"] for f in doc["findings"]} == {"src/signup.ts": "other", "tests/signup.test.ts": "test"}
    counts = {"total": 2, "service": 1, "non_service": 1, "by_role": {"other": 1, "test": 1}}
    assert doc["run"]["finding_counts"] == counts

    assert main(["scan", str(tmp_path), "--no-color"]) == 1
    out = capsys.readouterr().out
    aside = out.index("시험·픽스처·설정 파일의 발견 1건")
    assert out.index("src/signup.ts") < aside < out.index("tests/signup.test.ts")
    assert "그 가운데 시험·픽스처·설정 파일의 발견 1건" in out


def test_the_judge_is_not_asked_about_test_files(tmp_path, monkeypatch, capsys):
    """시험·픽스처 파일의 경고는 판정자에게 묻지 않는다(판정자가 없을 때처럼 남고 까닭은 test-file). 정책 팩 픽스처가
    많은 저장소에서 질문이 수백 개로 늘어 웹 실행기의 검사가 12분 걸렸다(11/11)."""
    import policypack.judge.anthropic_api as api
    from policypack.cli import main

    asked = []

    class Recording(FakeJudge):
        def ask(self, q):
            asked.append(q.code)
            return super().ask(q)

    monkeypatch.setattr(api, "build", lambda spec, **kw: Recording("예", echo_first_line=True))
    monkeypatch.setattr(api, "preflight", lambda spec: None)
    monkeypatch.chdir(tmp_path)
    for name in ("src/signup.ts", "tests/signup.test.ts"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIX / "pipa-22-2" / "violating.ts", tmp_path / name)
    main(["scan", str(tmp_path), "--judge", "anthropic:haiku", "--output-format", "json", "--exit-zero"])
    doc = json.loads(capsys.readouterr().out)
    check(doc)
    assert asked  # 서비스 코드는 묻는다
    by_role = {f["role"]: f for f in doc["findings"]}
    assert "test-file" in by_role["test"]["untested_reasons"] and by_role["test"]["ai_pending"]
    assert "test-file" not in by_role.get("other", {}).get("untested_reasons", [])
