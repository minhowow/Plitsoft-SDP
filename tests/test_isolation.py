"""사용자가 따로 쓰는 Semgrep 이 우리 실행에 스며들지 않는다 — 2026-09-25 검토에서 나온 결함들.

요약하면:

- CI 에 흔한 `SEMGREP_BASELINE_REF=main` 하나로 경고가 말없이 1건 → 0건이 됐다(종료 코드 0).
- 로그인 토큰(환경변수·settings.yml)이 엔진 출력을 바꿨고, 막아 주는 것은 플래그 둘뿐이었다.
- 실행할 때마다 사용자 HOME 의 `~/.semgrep/` 를 고쳐 썼다.
- 윈도에서 같은 환경의 `semgrep.exe` 를 찾지 못했다.
- AI 판정자가 파일 전체를 보내는데 실행 중에는 아무 말도 없었다.

네트워크 시험은 127.0.0.1 에만 붙는 기록용 프록시를 쓴다. 프록시는 받은 요청을 적고 403 으로
닫을 뿐 어디에도 전달하지 않는다. 토큰은 가짜 문자열이다.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

from policypack.cli import main
from policypack.static import semgrep_cli
from policypack.static.semgrep_cli import SemgrepBackend, _env

REPO = Path(__file__).resolve().parents[1]
VIOLATING = REPO / "policies/kr-core/tests/pipa-22-2/violating.ts"
FAKE_TOKEN = "fake-token-for-test"

#: 우리가 흉내 내는 "Semgrep 을 이미 쓰는 사용자"의 환경
HOSTILE = {
    "SEMGREP_APP_TOKEN": FAKE_TOKEN,
    "SEMGREP_BASELINE_REF": "main",
    "SEMGREP_BASELINE_COMMIT": "HEAD",
    "SEMGREP_TIMEOUT": "1",
    "SEMGREP_SEND_METRICS": "on",
    "SEMGREP_ENABLE_VERSION_CHECK": "1",
    "SEMGREP_URL": "https://semgrep.dev",
    "SEMGREP_SETTINGS_FILE": "/tmp/somebody-elses-settings.yml",
    "XDG_CONFIG_HOME": "/tmp/somebody-elses-config",
}


def _pack_config() -> dict:
    from policypack.pack.loader import load_pack
    from policypack.static.compile import compile_static

    return compile_static(load_pack(REPO / "policies" / "kr-core"))


def _pipa_matches(res) -> set[str]:
    return {m.key.predicate for m in res.matches if m.key.policy == "kr.pipa.22-2"}


# ── 환경 ────────────────────────────────────────────────────────────────────


def test_user_semgrep_settings_never_reach_the_engine(monkeypatch):
    for k, v in HOSTILE.items():
        monkeypatch.setenv(k, v)
    env = _env(Path("/x/bin/semgrep"))

    leaked = {"SEMGREP_APP_TOKEN", "SEMGREP_BASELINE_REF", "SEMGREP_BASELINE_COMMIT", "SEMGREP_TIMEOUT", "SEMGREP_URL"}
    assert not leaked & env.keys()
    assert "XDG_CONFIG_HOME" not in env and "XDG_CACHE_HOME" not in env
    # 우리가 다시 넣는 것만 남는다. 덮어쓴 값이 사용자 값을 이긴다
    assert env["SEMGREP_SEND_METRICS"] == "off"
    assert env["SEMGREP_ENABLE_VERSION_CHECK"] == "0"
    for key in ("SEMGREP_SETTINGS_FILE", "SEMGREP_LOG_FILE", "SEMGREP_VERSION_CACHE_PATH"):
        assert not env[key].startswith(str(Path.home())), key
        assert env[key] != HOSTILE.get(key)


def test_engine_selection_and_time_limits_are_ours(monkeypatch):
    """--oss-only 로 엔진을, --timeout·--timeout-threshold 로 시간 제한을 못박는다."""
    seen = {}

    def capture(cmd, **kw):
        seen["cmd"] = cmd
        raise RuntimeError("여기까지만")

    monkeypatch.setattr(subprocess, "run", capture)
    with pytest.raises(Exception, match="여기까지만"):
        SemgrepBackend(path=Path("/x/bin/semgrep")).run({"rules": []}, [VIOLATING])
    cmd = seen["cmd"]
    assert "--oss-only" in cmd
    assert cmd[cmd.index("--timeout") + 1] == SemgrepBackend.RULE_TIMEOUT == "5"
    assert cmd[cmd.index("--timeout-threshold") + 1] == SemgrepBackend.TIMEOUT_THRESHOLD == "3"


def _git_repo_with(tmp_path: Path, name: str, text: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / name).write_text(text, encoding="utf-8")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], check=True)
    return repo


@pytest.mark.parametrize("var,value", [("SEMGREP_BASELINE_REF", "main"), ("SEMGREP_BASELINE_COMMIT", "HEAD")])
def test_baseline_variables_cannot_hide_findings(tmp_path, monkeypatch, capsys, var, value):
    """Semgrep 공식 Jenkins 예시는 SEMGREP_BASELINE_REF="main" 을 파이프라인 전체 환경에 둔다.
    그 값이 우리 단계로 들어오면 semgrep 이 baseline 비교로 바뀌어 이미 있던 경고를 지웠다."""
    repo = _git_repo_with(tmp_path, "app.ts", VIOLATING.read_text(encoding="utf-8"))
    monkeypatch.chdir(repo)
    monkeypatch.setenv(var, value)
    code = main(["scan", "app.ts", "--output-format", "json", "--no-color"])
    report = json.loads(capsys.readouterr().out)
    assert code == 1
    assert [(f["policy"], f["rule"]) for f in report["findings"]] == [("kr.pipa.22-2", "signup-without-guard")]


def test_user_home_is_left_alone(tmp_path, monkeypatch):
    """pysemgrep 은 실행마다 ~/.semgrep/settings.yml 과 semgrep.log 를 만들거나 다시 쓴다."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    f = tmp_path / "a.ts"
    f.write_text(VIOLATING.read_text(encoding="utf-8"), encoding="utf-8")
    res = SemgrepBackend().run(_pack_config(), [f])
    assert {"signup-context", "birth-or-age"} <= _pipa_matches(res)
    assert list(home.iterdir()) == []


# ── 네트워크 ────────────────────────────────────────────────────────────────


class _RecordingProxy:
    """127.0.0.1 에만 붙는다. 요청 첫 줄만 적고 403 으로 닫는다. 아무것도 전달하지 않는다."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
        self.seen: list[str] = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(2)
                try:
                    head = conn.recv(4096)
                except OSError:
                    head = b""
                self.seen.append(head.split(b"\r\n", 1)[0].decode("latin-1"))
                with contextlib.suppress(OSError):
                    conn.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")

    def close(self) -> None:
        self.sock.close()


@pytest.fixture
def proxy(monkeypatch):
    p = _RecordingProxy()
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        monkeypatch.setenv(k, p.url)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    yield p
    p.close()


def test_the_proxy_actually_sees_outbound_attempts(proxy):
    """양성 대조. 이 프록시가 연결 시도를 잡는다는 것부터 확인한다(요청은 403 으로 끝난다)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"https": proxy.url}))
    with pytest.raises(OSError):
        opener.open("https://semgrep.dev/api/check-version", timeout=5)
    assert any(line.startswith("CONNECT semgrep.dev:443") for line in proxy.seen)


def test_no_outbound_attempt_even_when_the_user_is_logged_in(tmp_path, monkeypatch, proxy):
    """로그인하면 평범한 semgrep 은 metrics.semgrep.dev 로 보낸다(실측). 우리 실행은 0건이어야 한다."""
    home = tmp_path / "home"
    (home / ".semgrep").mkdir(parents=True)
    settings = home / ".semgrep" / "settings.yml"
    settings.write_text(f"api_token: {FAKE_TOKEN}\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    for k, v in HOSTILE.items():
        monkeypatch.setenv(k, v)

    f = tmp_path / "a.ts"
    f.write_text(VIOLATING.read_text(encoding="utf-8"), encoding="utf-8")
    backend = SemgrepBackend()
    backend.version()
    res = backend.run(_pack_config(), [f])

    assert proxy.seen == []
    # 결과도 그대로다. SEMGREP_BASELINE_*·SEMGREP_TIMEOUT 이 섞여 있어도 매치가 사라지지 않는다
    assert {"signup-context", "birth-or-age"} <= _pipa_matches(res)
    assert settings.read_text(encoding="utf-8") == f"api_token: {FAKE_TOKEN}\n"
    assert sorted(p.name for p in (home / ".semgrep").iterdir()) == ["settings.yml"]


# ── 실행 파일 찾기 ──────────────────────────────────────────────────────────


def test_windows_style_executable_is_found(tmp_path, monkeypatch):
    """윈도의 pip 는 Scripts\\semgrep.exe 를 만든다. 확장자 없는 이름만 찾으면 못 찾는다."""
    (tmp_path / "python.exe").write_text("", encoding="utf-8")
    exe = tmp_path / "semgrep.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    monkeypatch.delenv(semgrep_cli.ENV_VAR, raising=False)
    path, source, _ = semgrep_cli.resolve()
    assert path == exe
    assert "pip" in source


def test_non_venv_scripts_directory_is_searched(tmp_path, monkeypatch):
    """윈도의 python.org 설치본은 python.exe 옆이 아니라 Scripts\\ 에 semgrep.exe 를 둔다.
    pip install --user 도 사용자 스킴의 scripts 에 둔다. semgrep 자신도 sysconfig 로 짝을 찾는다."""
    base = tmp_path / "Python314"
    (base / "Scripts").mkdir(parents=True)
    (base / "python.exe").write_text("", encoding="utf-8")
    exe = base / "Scripts" / "semgrep.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(base / "python.exe"))
    monkeypatch.setattr(semgrep_cli.sysconfig, "get_path", lambda name, scheme=None: str(base / "Scripts"))
    monkeypatch.delenv(semgrep_cli.ENV_VAR, raising=False)
    path, source, _ = semgrep_cli.resolve()
    assert path == exe and "pip" in source
    # 같은 환경으로 본다(판본 기록이 패키지 판본과 대조된다)
    assert semgrep_cli.package_version(exe) is not None


def test_missing_engine_tells_users_how_to_reinstall(tmp_path, monkeypatch):
    """`uv sync` 는 이 저장소를 고치는 사람에게만 뜻이 있다."""
    (tmp_path / "python").write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
    monkeypatch.setattr(semgrep_cli.sysconfig, "get_path", lambda name, scheme=None: str(tmp_path))
    monkeypatch.delenv(semgrep_cli.ENV_VAR, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    path, _, notes = semgrep_cli.resolve()
    assert path is None
    assert "uv sync" not in " ".join(notes)
    assert "reinstall" in " ".join(notes)


def test_reinstall_hint_never_installs_by_bare_registry_name():
    """아직 PyPI 에 없는 이름으로 설치하라고 하면, 누가 그 이름을 먼저 등록할 때 제3자 패키지가 깔린다.
    처음 설치한 원천을 다시 쓰는 명령만 안내한다."""
    import re

    hint = semgrep_cli.REINSTALL_HINT
    assert not re.search(r"(uv tool install|pip install|pipx install)[^·)]*\bpolicypack\b", hint)
    assert "uv tool upgrade --reinstall policypack" in hint and "pipx reinstall policypack" in hint


# ── AI 판정자 ───────────────────────────────────────────────────────────────


def test_live_judge_announces_what_leaves_the_machine(tmp_path, monkeypatch, capsys):
    """판정자를 켜면 파일 전체가 나간다. 실행할 때 그 사실을 한 줄로 알린다.

    가짜 claude CLI 를 쓴다. 받은 입력을 버리고 '아니오'를 돌려줄 뿐 네트워크에 닿지 않는다.
    """
    fake = tmp_path / "fake_claude"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "sys.stdin.read()\n"
        "print(json.dumps({'is_error': False, 'num_turns': 1, 'total_cost_usd': 0,\n"
        "                  'result': json.dumps({'answer': '아니오', 'evidence': ''})}))\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    import policypack.judge.claude_cli as claude_cli

    monkeypatch.setattr(claude_cli, "BIN", str(fake))
    target = tmp_path / "a.js"
    target.write_text("const a = 1;\n", encoding="utf-8")
    main(["scan", str(target), "--judge", "claude-cli:haiku", "--no-color"])
    err = capsys.readouterr().err
    assert "AI 판정자 claude-cli:haiku" in err
    assert "전체 내용" in err and "1MB 미만" in err


def test_notice_states_what_is_sent():
    """약한 근거로만 준수가 보이는 파일도 판정자에게 간다. 고지가 그 범위를 말해야 한다."""
    from policypack.cli import _egress_notice

    assert "약한 근거로만 준수가 보이는 파일 포함" in _egress_notice("claude-cli:haiku", env={})


def test_notice_names_the_real_destination_and_telemetry():
    """판정자 CLI 는 사용자의 게이트웨이·텔레메트리 설정을 따른다. 끊지 않고 알린다."""
    from policypack.cli import _egress_notice

    env = {"ANTHROPIC_BASE_URL": "https://gw.example.invalid", "OTEL_LOG_USER_PROMPTS": "1"}
    text = _egress_notice("claude-cli:haiku", env=env)
    assert "ANTHROPIC_BASE_URL=https://gw.example.invalid" in text
    assert "OTEL_LOG_USER_PROMPTS" in text
    assert "ANTHROPIC_BASE_URL" not in _egress_notice("claude-cli:haiku", env={})


def test_sigterm_cleans_up_temp_files(tmp_path):
    """CI 취소나 `timeout` 으로 끝나도 설정 임시 파일과 semgrep 상태 디렉터리가 남지 않는다."""
    import signal
    import time

    tmp = tmp_path / "tmp"
    tmp.mkdir()
    env = {**os.environ, "TMPDIR": str(tmp)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "policypack", "scan", str(REPO / "policies" / "kr-core" / "tests")],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 60
    while time.time() < deadline and not list(tmp.glob("policypack-semgrep-*")):
        time.sleep(0.05)
    assert list(tmp.glob("policypack-semgrep-*")), "semgrep 이 시작되지 않았다"
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=60)
    assert proc.returncode == 128 + signal.SIGTERM
    assert not list(tmp.glob("policypack-semgrep-*"))
    assert not list(tmp.glob("tmp*.yaml"))


def test_no_notice_without_a_live_judge(tmp_path, capsys):
    target = tmp_path / "a.js"
    target.write_text("const a = 1;\n", encoding="utf-8")
    main(["scan", str(target), "--no-color"])
    assert "AI 판정자" not in capsys.readouterr().err


def test_semgrep_temp_files_live_in_our_state_dir():
    """신호로 끊기면 semgrep 이 대상 목록·규칙 임시 파일을 지우지 못하고 사용자 임시 폴더에 남겼다(실측)."""
    env = _env(Path("/x/bin/semgrep"))
    assert Path(env["TMPDIR"]) == Path(env["SEMGREP_SETTINGS_FILE"]).parent


def test_a_user_scheme_semgrep_is_not_ours_inside_a_venv(monkeypatch):
    """venv 에서는 사용자 site 가 꺼져 있다. ~/.local/bin 의 다른 semgrep 을 '이 환경에 설치된 판'이라 적었다."""
    import site
    import sysconfig

    from policypack.static import semgrep_cli

    monkeypatch.setattr(site, "ENABLE_USER_SITE", False)
    user = sysconfig.get_path("scripts", f"{os.name}_user")
    assert Path(user) not in semgrep_cli._env_dirs() or Path(user) == Path(sysconfig.get_path("scripts"))


@pytest.mark.parametrize(
    "var,value,msg",
    [
        ("POLICYPACK_SEMGREP", "DIR", "실행할 수 있는 파일이 아닙니다"),
        ("POLICYPACK_SEMGREP_TIMEOUT", "abc", "0보다 큰 초 단위 숫자"),
        ("POLICYPACK_SEMGREP_TIMEOUT", "-1", "0보다 큰 초 단위 숫자"),
    ],
)
def test_bad_engine_settings_are_clear_errors(tmp_path, monkeypatch, capsys, var, value, msg):
    """traceback 대신 오류 한 줄과 종료 코드 2."""
    from policypack.cli import main

    monkeypatch.setenv(var, str(tmp_path) if value == "DIR" else value)
    (tmp_path / "a.ts").write_text("export const a = 1;\n", encoding="utf-8")
    assert main(["scan", str(tmp_path / "a.ts")]) == 2
    err = capsys.readouterr().err
    assert msg in err and "Traceback" not in err


def test_a_target_the_engine_did_not_scan_is_not_clean(tmp_path, monkeypatch):
    """규칙의 언어에 드는 대상을 엔진이 오류 없이 건너뛰었다면 그 '매치 없음'은 거짓이 아니라 '모름'이다. 어떤 규칙의
    언어도 아닌 파일은 볼 규칙이 없어 건너뛴 것이라 세지 않는다."""
    js, js2, sh = tmp_path / "a.js", tmp_path / "b.js", tmp_path / "c.sh"
    config = {"rules": [{"id": "kr.p.r.pred", "languages": ["javascript"], "pattern": "send(...)"}]}
    engine_json = {"version": "1.176.1", "results": [], "errors": [], "paths": {"scanned": [str(js)]}}
    monkeypatch.setattr(SemgrepBackend, "raw", lambda self, config, targets: (engine_json, 0.1))
    res = SemgrepBackend(Path("/x/bin/semgrep")).run(config, [js, js2, sh])
    assert res.incomplete == {js2}


def test_a_relative_engine_path_is_made_absolute(tmp_path, monkeypatch):
    """semgrep 은 대상 폴더에서 돈다. 상대 경로를 그대로 두면 다른 파일을 불렀다(검토에서 실측: 검사하는 트리 안의
    bin/semgrep)."""
    from policypack.static.semgrep_cli import resolve

    (tmp_path / "bin").mkdir()
    engine = tmp_path / "bin" / "semgrep"
    engine.write_text("#!/bin/sh\n", encoding="utf-8")
    engine.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("POLICYPACK_SEMGREP", "bin/semgrep")
    path, _, _ = resolve()
    assert path.is_absolute() and path == engine.absolute()


def test_an_empty_timeout_setting_means_the_default(monkeypatch):
    """CI 의 설정 안 된 변수는 빈 값이다. 빈 POLICYPACK_SEMGREP 처럼 없는 것으로 본다."""
    from policypack.static.semgrep_cli import SemgrepBackend, timeout_from_env

    monkeypatch.setenv("POLICYPACK_SEMGREP_TIMEOUT", "")
    assert timeout_from_env() == SemgrepBackend.DEFAULT_TIMEOUT
