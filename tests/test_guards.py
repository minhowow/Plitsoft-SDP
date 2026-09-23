"""말없이 규칙을 끄는 경로를 막는다.

`// nosemgrep` 은 semgrep 이 스스로 매치를 지우는 주석이다. 사용자 코드에 있으면 우리
적용 조건의 매치가 사라져 규칙이 흔적 없이 꺼졌다(실측). 그래서 `--disable-nosem` 으로
돌린다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from policypack.cli import main
from policypack.pack.loader import load_pack

REPO = Path(__file__).resolve().parents[1]


def test_nosemgrep_does_not_switch_a_policy_off(tmp_path, monkeypatch, capsys):
    """적용 조건(ad-marker·send-call)의 매치가 지워지면 규칙 전체가 '해당 없음'이 됐다."""
    (tmp_path / "blast.ts").write_text(
        "export async function blast(users) {\n"
        '  for (const u of users) await sms.send(u.phone, "(광고) 가을 세일"); // nosemgrep\n'
        "}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert main(["scan", "blast.ts", "--no-color", "--output-format", "concise"]) == 1
    assert "야간" in capsys.readouterr().out


@pytest.mark.parametrize("root", ["policies", "tests/data"])
def test_no_suppression_comments_in_our_own_data(root):
    """semgrep 은 --disable-nosem 으로 돌지만, 팩 픽스처에 억제 주석이 들어오면 엔진 설정에 따라 매치 집합이
    달라진다. 아예 없게 둔다."""
    hits = [
        str(p.relative_to(REPO))
        for p in (REPO / root).rglob("*")
        if p.is_file() and p.suffix in {".js", ".jsx", ".ts", ".tsx", ".yaml"}
        for token in ("nosemgrep", "policypack-ignore")
        if token in p.read_text(encoding="utf-8", errors="replace")
    ]
    assert hits == []


def test_ai_alternatives_must_cite(tmp_path):
    """인용 없는 '예' 하나가 경고를 내리면 방향성 신뢰가 깨진다. AI 대안의 evidence 는 required·strict 뿐이다."""
    from policypack.errors import PackError

    src = (REPO / "policies/kr-core/pack.yaml").read_text(encoding="utf-8")
    (tmp_path / "pack.yaml").write_text(src.replace("evidence: required", "evidence: optional", 1), encoding="utf-8")
    with pytest.raises(PackError, match="'required' or 'strict'"):
        load_pack(tmp_path)


def test_ai_predicates_are_refused_in_applies_when(tmp_path):
    """applies-when 의 AI 조건은 묻지 않고 거짓이 되어 규칙을 끈다. 문법이 막는다."""
    from policypack.errors import PackError

    src = (REPO / "policies/kr-core/pack.yaml").read_text(encoding="utf-8")
    src = src.replace(
        "          - id: birth-or-age\n",
        "          - id: is-signup\n            ai:\n              question: 가입인가?\n          - id: birth-or-age\n",
        1,
    )
    (tmp_path / "pack.yaml").write_text(src, encoding="utf-8")
    with pytest.raises(PackError, match="applies-when 은 정적 조건만"):
        load_pack(tmp_path)


def test_weak_evidence_cannot_clear_without_a_judge(tmp_path, monkeypatch, capsys):
    """판정자가 없으면 이름(guardian-call)만으로 경고가 풀리면 안 된다. 불확실로 남고 AI 차례였다고 알린다."""
    src = (REPO / "policies/kr-core/tests/pipa-22-2/guardian-call.ts").read_text(encoding="utf-8")
    (tmp_path / "a.ts").write_text(src, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    code = main(["scan", "a.ts", "--no-color", "--output-format", "concise"])
    out = capsys.readouterr()
    assert code == 1 and "불확실" in out.out
    assert "AI 확인이 필요한 곳 1건" in out.out and "판정자가 꺼져 있습니다" in out.out


def test_strict_evidence_refuses_a_citation_that_carries_a_comment(tmp_path):
    """'이 문구가 코드에 있는가'를 묻는 조건. required 는 줄 끝 주석이 달린 코드 줄의 인용을 코드 부분으로
    받는다. strict 는 주석이 닿은 인용을 받지 않는다."""
    from policypack.evaluate.engine import Target, evaluate
    from policypack.judge.fake import FakeJudge
    from policypack.model import Evidence
    from policypack.static.compile import compile_static
    from policypack.static.semgrep_cli import SemgrepBackend

    line = "await gateway.enforceQuietHours(); // 야간 발송 차단"
    f = tmp_path / "blast.ts"
    f.write_text(
        "export async function blast(users) {\n"
        f"  {line}\n"
        '  for (const u of users) await sms.send(u.phone, "(광고) 가을 세일");\n}\n',
        encoding="utf-8",
    )
    pack = load_pack(REPO / "policies/kr-core")
    target = [Target(path=f, lang="typescript")]
    static = SemgrepBackend().run(compile_static(pack), [f])
    judge = FakeJudge("예", evidence=line)

    def outcome(p):
        res = evaluate(p, target, static, judge=judge)
        night = [x.outcome.value for x in res.findings if x.policy == "kr.network-act.50-3"]
        return night[0] if night else "compliant"

    pol = next(p for p in pack.policies if p.id == "kr.network-act.50-3")
    rule = pol.rules[0]
    assert next(p for p in rule.compliant_if_any if p.is_ai).ai.evidence is Evidence.REQUIRED
    assert outcome(pack) == "compliant", "required 는 코드 부분이 실재하면 받는다"
    alts = [
        p.model_copy(update={"ai": p.ai.model_copy(update={"evidence": Evidence.STRICT})}) if p.is_ai else p
        for p in rule.compliant_if_any
    ]
    strict = pack.model_copy(
        update={
            "policies": [
                q.model_copy(update={"rules": [rule.model_copy(update={"compliant_if_any": alts})]})
                if q.id == "kr.network-act.50-3"
                else q
                for q in pack.policies
            ]
        }
    )
    assert outcome(strict) == "needs-review-uncertain"


# ── 배포 경계 ───────────────────────────────────────────────────────────────
# 아래 셋은 법적 경계다. 한 번 뚫리면 되돌리기 어렵다.
#   1. 레지스트리 규칙을 들이면 Semgrep Rules License 가 걸려 공개 배포가 막힌다
#   2. 정적 검사가 밖으로 나가면 semgrep.dev 약관 안으로 들어가고, 약속도 깨진다
#   3. 어느 엔진이 돌았는지 모르면 보고서가 무엇의 결과인지 알 수 없다

REGISTRY = re.compile(r"""--config[ =]['"]?(p|r)/|\bconfig:\s*['"]?(p|r)/|semgrep\.dev/(p|r)/|--config[ =]auto\b""")


def test_no_registry_rules_anywhere():
    """Semgrep Registry 규칙은 "internal business purposes" 전용이라 배포·서비스 제공이 금지된다.
    한 건이라도 들이면 이 도구를 공개할 수 없다."""
    roots = ["src", "policies", "Makefile", ".pre-commit-hooks.yaml"]
    hits = []
    for root in roots:
        p = REPO / root
        files = (
            [p]
            if p.is_file()
            else [f for f in p.rglob("*") if f.is_file() and f.suffix in {".py", ".yaml", ".yml", ""}]
        )
        for f in files:
            text = f.read_text(encoding="utf-8", errors="replace")
            if REGISTRY.search(text):
                hits.append(str(f.relative_to(REPO)))
    assert hits == [], f"레지스트리 규칙 참조: {hits}"


def test_no_registry_derived_rules_are_tracked():
    """공식 규칙이나 그것을 감싼 팩(수정본 고지가 붙어 있다)이 저장소에 들어오면, 저장소를 공개하는
    순간 Semgrep Rules License 가 금지한 배포가 된다. 추적 중인 YAML·JSON 에 출처 표지와 규칙 문법이
    함께 있으면 실패한다.
    """
    import subprocess

    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, check=True).stdout
    markers = ("semgrep-rules", "Semgrep Rules License", "eval_notice")
    # 글 속 단어가 아니라 규칙의 키 모양일 때만 센다(주석·문서는 규칙 기능을 글로 설명할 수 있다)
    keys = r"(pattern-either|pattern-sources|pattern-sinks|pattern-inside|patterns|pattern)"
    yaml_key = re.compile(rf"(?m)^\s*(-\s+)?{keys}\s*:")
    json_key = re.compile(rf'"{keys}"\s*:')
    hits = []
    for rel in tracked.decode().split("\0"):
        if not rel.endswith((".yaml", ".yml", ".json")):
            continue
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        shaped = json_key if rel.endswith(".json") else yaml_key
        if any(m in text for m in markers) and shaped.search(text):
            hits.append(rel)
    assert hits == [], f"공식 규칙에서 파생한 파일이 저장소에 있다: {hits}"


def test_scan_never_enables_telemetry_or_version_check(monkeypatch):
    """정적 검사가 밖으로 나가지 않는다. 플래그만으로는 부족하다 — `semgrep --version` 은
    플래그가 없으면 판본 확인을 하러 나간다(실측)."""
    import subprocess

    from policypack.static.semgrep_cli import SemgrepBackend, _env

    env = _env(Path("/x/bin/semgrep"))
    assert env["SEMGREP_SEND_METRICS"] == "off"
    assert env["SEMGREP_ENABLE_VERSION_CHECK"] == "0"

    seen = {}

    def capture(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw.get("env", {})
        raise RuntimeError("여기까지만")

    monkeypatch.setattr(subprocess, "run", capture)
    with pytest.raises(Exception, match="여기까지만|semgrep"):
        SemgrepBackend().run({"rules": []}, [REPO / "README.md"])
    assert "--metrics=off" in seen["cmd"] and "--disable-version-check" in seen["cmd"]
    assert seen["env"]["SEMGREP_SEND_METRICS"] == "off"


def test_engine_is_pinned_to_the_executable_we_chose():
    """semgrep 진입점은 실제 구현을 PATH 에서도 찾는다. 이 머신에는 Homebrew 판이 함께 있어서,
    PATH 를 고정하지 않으면 venv 의 판본을 절대경로로 불러도 다른 엔진이 돌았다(실측)."""
    from policypack.static.semgrep_cli import _env, resolve

    path, _, _ = resolve()
    assert path is not None
    assert _env(path)["PATH"].split(os.pathsep)[0] == str(path.parent)


def test_recorded_engine_version_comes_from_the_run(tmp_path):
    """--version 을 따로 묻지 않고, 그 실행이 스스로 밝힌 판본을 적는다."""
    from policypack.static.compile import compile_static
    from policypack.static.semgrep_cli import EXPECTED_VERSION, SemgrepBackend

    f = tmp_path / "a.js"
    f.write_text("const x = 1;\n", encoding="utf-8")
    res = SemgrepBackend().run(compile_static(load_pack(REPO / "policies/kr-core")), [f])
    assert res.backend_version.startswith(EXPECTED_VERSION)


def test_scan_has_a_time_limit(monkeypatch, tmp_path):
    """시간 제한이 없으면 semgrep 이 멈출 때 커밋 훅과 CI 가 함께 멈춘다."""
    import subprocess

    from policypack.errors import BackendError
    from policypack.static.semgrep_cli import SemgrepBackend

    backend = SemgrepBackend()
    assert backend.timeout > 0

    def hang(*a, **kw):
        assert kw.get("timeout") == backend.timeout
        raise subprocess.TimeoutExpired(cmd="semgrep", timeout=kw["timeout"])

    monkeypatch.setattr(subprocess, "run", hang)
    f = tmp_path / "a.js"
    f.write_text("const x = 1;\n", encoding="utf-8")
    with pytest.raises(BackendError, match="초 안에 끝나지 않았습니다"):
        backend.run({"rules": []}, [f])


def test_notice_and_readme_state_the_licence():
    """`pip install` 이 LGPL 프로그램을 함께 설치한다는 사실이 사용자에게 보여야 한다."""
    notice = (REPO / "NOTICE").read_text(encoding="utf-8")
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for needle in ("LGPL-2.1", "MIT", "Registry"):
        assert needle in notice
    assert "## 라이선스와 배포" in readme
    assert "LGPL-2.1" in readme


def test_a_path_that_does_not_exist_is_an_error(tmp_path, monkeypatch, capsys):
    """CI 에서 경로를 오타내면 조용히 통과하면 안 된다."""
    monkeypatch.chdir(tmp_path)
    assert main(["scan", "src/nope", "--no-color"]) == 2
    assert "경로가 없습니다" in capsys.readouterr().err
