"""Semgrep 을 서브프로세스로 부르는 백엔드.

## 실행 파일을 고르는 순서

이 머신에는 homebrew 판(`/opt/homebrew/bin/semgrep`)과 패키지가 동봉한 판
(`.venv/bin/semgrep`)이 함께 있다. 둘이 섞이면 어느 엔진이 낸 판정인지 알 수 없게
되므로 순서를 고정한다.

1. `POLICYPACK_SEMGREP` 환경변수 — 사용자가 명시한 것이 가장 세다
2. 우리 파이썬 환경에 설치된 판 — `pip install semgrep` 이 휠에 동봉한 것
3. `PATH` 의 것 — 버전이 다르면 경고한다
4. 없으면 종료 코드 2

`which` 를 먼저 보지 않는 것이 핵심이다. 엔진 이름과 판본은 보고서(JSON·SARIF·요약)에 기록한다.
"""

from __future__ import annotations

import atexit
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path

from policypack.errors import BackendError
from policypack.static.backend import StaticResult
from policypack.static.parse import TIMEOUT_THRESHOLD, parse_semgrep_json, rule_table

#: 시험한 판. 판이 다르면 같은 팩의 판정이 달라질 수 있어 경고한다(막지는 않는다).
EXPECTED_VERSION = "1.176"

ENV_VAR = "POLICYPACK_SEMGREP"

#: 사용자에게 보여 줄 설치 안내. `uv sync` 는 이 저장소를 고치는 사람에게만 뜻이 있다.
#:
#: 이름만으로 설치하는 명령(`uv tool install --reinstall policypack`, `pip install policypack`)은 쓰지 않는다.
#: 아직 PyPI 에 올리지 않은 이름이라 레지스트리에서 찾게 되고, 누가 그 이름을 먼저 등록하면 제3자
#: 패키지가 설치된다. `uv tool upgrade --reinstall` 과 `pipx reinstall` 은 처음 설치한
#: 원천(경로·git URL)을 다시 쓴다(실측).
REINSTALL_HINT = (
    "policypack 을 처음 설치한 곳에서 다시 설치하세요(uv tool upgrade --reinstall policypack · "
    f"pipx reinstall policypack). 다른 semgrep 을 쓰려면 {ENV_VAR} 에 실행 파일 경로를 주세요."
)

#: 같은 환경에서 찾을 실행 파일 이름. 윈도의 pip 는 `Scripts\semgrep.exe` 를 만든다.
#: 확장자 없는 이름만 찾으면 윈도에서 pipx·uv tool 로 설치한 사용자가 "semgrep 을 찾지
#: 못했습니다"를 보거나 PATH 의 다른 판을 쓰게 된다.
_EXE_NAMES = ("semgrep", "semgrep.exe")


def _env_dirs() -> list[Path]:
    """우리 파이썬 환경의 실행 파일 디렉터리들.

    venv 에서는 python 과 semgrep 이 같은 디렉터리에 있다. venv 가 아니면 다르다 — 윈도의 python.org
    설치본은 `python.exe` 옆이 아니라 `Scripts\\` 에, `pip install --user` 는 사용자 스킴의 scripts 에
    둔다. semgrep 자신의 진입점도 `sysconfig.get_path("scripts")` 로 짝을 찾는다.
    """
    dirs = [Path(sys.executable).parent]
    for scheme in (None, f"{os.name}_user"):
        try:
            d = sysconfig.get_path("scripts", scheme) if scheme else sysconfig.get_path("scripts")
        except KeyError:
            continue
        if d and Path(d) not in dirs:
            dirs.append(Path(d))
    return dirs


def _bundled() -> Path | None:
    """우리 파이썬 환경에 설치된 semgrep 실행 파일."""
    for here in _env_dirs():
        for name in _EXE_NAMES:
            candidate = here / name
            if candidate.is_file():
                return candidate
    return None


def resolve() -> tuple[Path | None, str, list[str]]:
    """(실행 파일, 고른 이유, 경고 목록)."""
    notes: list[str] = []

    override = os.environ.get(ENV_VAR)
    if override:
        p = Path(override)
        if not p.exists():
            raise BackendError(f"{ENV_VAR} 가 가리키는 파일이 없습니다: {p}")
        return p, f"{ENV_VAR} 환경변수", notes

    bundled = _bundled()
    if bundled:
        return bundled, "이 파이썬 환경에 설치된 판 (pip 휠 동봉)", notes

    found = shutil.which("semgrep")
    if found:
        notes.append(
            f"PATH 의 semgrep 을 씁니다({found}). policypack 과 함께 설치된 판이 없어 버전이 고정되지 않습니다. "
            + REINSTALL_HINT
        )
        return Path(found), "PATH", notes

    return None, "찾지 못함", ["semgrep 이 없습니다. " + REINSTALL_HINT]


#: semgrep 이 사용자 상태를 찾는 위치를 바꾸는 키. `SEMGREP_` 로 시작하지 않아 따로 뺀다.
_DROP_EXACT = frozenset({"XDG_CONFIG_HOME", "XDG_CACHE_HOME"})

_STATE: Path | None = None


def _state_dir() -> Path:
    """semgrep 의 settings·로그·판본 캐시를 둘 전용 임시 디렉터리. 프로세스가 끝나면 지운다
    (SIGTERM 도 cli.main 이 정상 종료로 바꾼다. SIGKILL 이면 남는다).

    pysemgrep 은 실행마다 `~/.semgrep/settings.yml`(익명 사용자 ID)과 `semgrep.log` 를 만들거나
    다시 쓴다. 그 파일에는 사용자가 `semgrep login` 으로 남긴 토큰도 들어 있다. 우리 실행은
    사용자 HOME 을 읽지도 쓰지도 않는다.
    """
    global _STATE
    if _STATE is None or not _STATE.exists():
        _STATE = Path(tempfile.mkdtemp(prefix="policypack-semgrep-"))
        atexit.register(shutil.rmtree, _STATE, True)
    return _STATE


def _env(path: Path | None = None) -> dict[str, str]:
    """semgrep 서브프로세스의 환경.

    - **사용자가 semgrep 에 해 둔 설정은 물려주지 않는다.** `SEMGREP_` 로 시작하는 변수를 모두 빼고,
      settings·로그·판본 캐시는 전용 임시 디렉터리를 가리킨다. 실측: CI 에 흔한
      `SEMGREP_BASELINE_REF=main`·`SEMGREP_BASELINE_COMMIT` 하나로 semgrep 이 baseline 비교로
      바뀌어 경고가 말없이 1건 → 0건이 됐다(종료 코드 0). 로그인 토큰(`SEMGREP_APP_TOKEN`,
      settings 의 api_token)은 엔진 출력을 바꾸고, `SEMGREP_TIMEOUT` 은 우리가 정한 것과 다른 시간
      제한을 만든다. 우리가 부르는 도구의 동작은 우리가 정한다.

    - PATH: 우리가 고른 실행 파일의 디렉터리를 맨 앞에 둔다. semgrep 의 진입점은 실제 구현
      (pysemgrep·semgrep-core)을 PATH 에서도 찾는다. 실측: 이 머신에는 Homebrew 판 1.176.0 이
      함께 있어서, venv 의 1.176.1 을 절대경로로 불러도 출력 JSON 의 version 이 1.176.0 으로
      나왔다. 판정이 엔진 판에 달린 도구가 어느 엔진이 돌았는지 모르면 안 된다.

    - PYTHONUTF8: semgrep(파이썬 래퍼)이 설정 파일을 로캘 인코딩으로 읽지 않게 한다.
      규칙 메시지에 한글이 있다. CP949 로캘의 윈도에서는 그대로 두면 설정을 못 읽는다.
    - 나머지 둘은 **법적 경계**다. 이 도구는 남의 소스 코드를 읽는다. 아무것도 밖으로 보내지
      않는다는 것이 semgrep.dev 약관 밖에 머무는 근거이자 사용자에게 한 약속이다.
      명령줄 플래그만으로는 부족하다 — `semgrep --version` 은 플래그가 없으면 버전 확인을
      하러 나간다(실측: "A new version of Semgrep is available" 안내가 붙는다).
    """
    state = _state_dir()
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("SEMGREP_") and k not in _DROP_EXACT}
    env.update(
        {
            "PYTHONUTF8": "1",
            "SEMGREP_ENABLE_VERSION_CHECK": "0",
            "SEMGREP_SEND_METRICS": "off",
            "SEMGREP_SETTINGS_FILE": str(state / "settings.yml"),
            "SEMGREP_LOG_FILE": str(state / "semgrep.log"),
            "SEMGREP_VERSION_CACHE_PATH": str(state / "semgrep_version"),
        }
    )
    if path is not None:
        env["PATH"] = os.pathsep.join([str(path.parent), env.get("PATH", "")])
    return env


def _json_default(x):
    # YAML 이 날짜로 읽은 값. semgrep 도 ISO 문자열로 낸다.
    if isinstance(x, (datetime.date, datetime.datetime)):
        return x.isoformat()
    raise TypeError(f"{type(x).__name__} 값은 semgrep 설정에 쓸 수 없습니다: {x!r}")


_VERSION_LINE = re.compile(r"^\d+\.\d+\.\d+")


def version_of(path: Path) -> str:
    """실행 파일이 스스로 밝히는 판본. 안내 문구가 섞여 나오므로 판본처럼 생긴 줄만 고른다."""
    try:
        out = subprocess.run(
            [str(path), "--version", "--disable-version-check"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            env=_env(path),
        )
    except Exception as e:  # noqa: BLE001
        raise BackendError(f"semgrep --version 실패: {e}") from e
    lines = [ln.strip() for ln in ((out.stdout or "") + "\n" + (out.stderr or "")).splitlines() if ln.strip()]
    for line in lines:
        if _VERSION_LINE.match(line):
            return line
    raise BackendError(f"semgrep 판본을 읽지 못했습니다: {lines[:3]}")


def package_version(path: Path) -> str | None:
    """이 실행 파일이 우리 파이썬 환경의 것이면 설치된 배포판의 판본.

    CLI 가 말하는 판본과 패키지 판본이 어긋날 수 있다(포장만 다시 한 릴리스 등). 재현성을
    따지는 도구가 엔진을 틀리게 적으면 안 되므로, 다르면 둘 다 기록한다.
    """
    # sys.executable 은 심볼릭 링크다(.venv/bin/python → 시스템 파이썬). resolve 하면 venv 를
    # 벗어나 비교가 늘 어긋난다. 링크를 따라가지 않고 견준다.
    if path.parent not in _env_dirs():
        return None
    try:
        from importlib.metadata import version

        return version("semgrep")
    except Exception:  # noqa: BLE001
        return None


def engine_id(path: Path) -> str:
    """결과에 남길 엔진 이름. CLI 가 말하는 판본과 설치된 패키지 판본이 다르면 둘 다 적는다."""
    cli = version_of(path)
    pkg = package_version(path)
    return cli if not pkg or pkg == cli else f"{cli} (패키지 {pkg})"


def diagnose() -> dict:
    """`policypack doctor` 가 쓰는 진단 정보."""
    try:
        path, source, notes = resolve()
    except BackendError as e:
        return {"path": None, "version": None, "source": "오류", "notes": [str(e)]}
    if path is None:
        return {"path": None, "version": None, "source": source, "notes": notes}
    version = engine_id(path)
    if not version.startswith(EXPECTED_VERSION):
        notes.append(
            f"버전이 {version} 입니다. policypack 은 {EXPECTED_VERSION}.x 로 시험했습니다. "
            f"엔진 판이 다르면 같은 팩의 판정이 달라질 수 있습니다."
        )
    return {"path": str(path), "version": version, "source": source, "notes": notes}


class SemgrepBackend:
    name = "semgrep"

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            path, _, _ = resolve()
            if path is None:
                raise BackendError("semgrep 을 찾지 못했습니다. " + REINSTALL_HINT)
        self.path = path
        self._version: str | None = None
        self.timeout = float(os.environ.get("POLICYPACK_SEMGREP_TIMEOUT", self.DEFAULT_TIMEOUT))

    def version(self) -> str:
        if self._version is None:
            self._version = engine_id(self.path)
        return self._version

    #: 한 번에 넘길 파일 수. 명령줄 길이 제한(ARG_MAX)에 걸리지 않게 나눠 부른다.
    CHUNK = 1500

    #: 한 번 실행의 시간 제한(초). 규칙 하나의 시간 초과는 semgrep 이 스스로 다루지만,
    #: 프로세스 자체가 멈추면 훅과 CI 가 함께 멈춘다.
    DEFAULT_TIMEOUT = 900

    #: 규칙 하나가 파일 하나에 쓸 수 있는 시간(초)과, 그런 시간 초과가 몇 번이면 그 파일을
    #: 건너뛰는지. semgrep 1.176 의 기본값이다. 명시하지 않으면
    #: 사용자의 `SEMGREP_TIMEOUT` 이 끼어든다. 문턱은 parse.py 가 결과를 읽을 때 쓰는 값과 같아야 한다.
    RULE_TIMEOUT = "5"
    TIMEOUT_THRESHOLD = str(TIMEOUT_THRESHOLD)

    def run(self, config: dict, targets: list[Path]) -> StaticResult:
        """targets 는 **파일 목록**이다. 디렉터리를 넘기지 않는다.

        semgrep 은 디렉터리를 받으면 자체 규칙으로 경로를 걸러 낸다. 실측: 이름이 `test` 인
        디렉터리가 통째로 빠졌다. 무엇을 볼지는 우리가 정해야 한다. 사용자의 test 디렉터리를 말없이 건너뛰는
        법 검토 도구는 쓸모가 없다.
        """
        if len(targets) > self.CHUNK:
            merged = StaticResult(backend=self.name)
            versions: list[str] = []
            for i in range(0, len(targets), self.CHUNK):
                part = self._run_once(config, targets[i : i + self.CHUNK])
                versions.append(part.backend_version)
                merged.absorb(part)
            # 한 번 돌린 것과 같은 출처(엔진이 JSON 에 밝힌 판본)를 쓴다. 판마다 다르면 모두 적는다
            merged.backend_version = ",".join(dict.fromkeys(v for v in versions if v))
            return merged
        return self._run_once(config, targets)

    def _run_once(self, config: dict, targets: list[Path]) -> StaticResult:
        data, elapsed = self.raw(config, targets)
        result = parse_semgrep_json(data, rule_table(config))
        if result.unlocated_errors:
            # 어느 파일인지 모르는 파일 단위 오류: 이 실행의 대상 어느 것의 '거짓'도 믿을 수 없다.
            # 파싱 실패와 달리 정규식 사본까지 믿지 않는다(incomplete)
            result.incomplete |= set(targets)
        result.runs = 1
        result.elapsed_s = elapsed
        result.backend = self.name
        # 엔진이 스스로 밝힌 판본을 적는다. --version 을 따로 묻는 것보다 이게 실제로 돈 엔진이다
        result.backend_version = str(data.get("version") or "") or self.version()
        return result

    def raw(self, config: dict, targets: list[Path]) -> tuple[dict, float]:
        """semgrep 이 낸 JSON 그대로와 걸린 시간. 나누지 않는다(_run_once 와 시험이 쓴다)."""
        # 설정을 JSON 으로 쓴다. JSON 은 YAML 의 부분집합이라 semgrep 이 그대로 읽고,
        # 문자열이 항상 따옴표에 싸여서 YAML 1.1 의 yes/no/on/off 강제변환을 아예 피한다.
        # 패턴 안에 on 이나 no 가 들어가도 안전하다.
        # 먼저 직렬화한다. 도중에 실패하면 반쯤 쓴 임시 파일이 남는다.
        try:
            payload = json.dumps(config, ensure_ascii=False, default=_json_default)
        except (TypeError, ValueError) as e:
            raise BackendError(f"semgrep 설정을 만들지 못했습니다: {e}") from e
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(payload)
            cfg = f.name
        cmd = [
            str(self.path),
            "scan",
            "--config",
            cfg,
            "--json",
            "--metrics=off",
            "--disable-version-check",
            # 사용자 코드의 `// nosemgrep` 주석이 우리 조건의 매치를 지우지 못하게 한다.
            # 지우면 적용 조건이 거짓이 되어 규칙이 흔적 없이 꺼진다(실측).
            "--disable-nosem",
            # 로그인해 있어도 오픈 소스 엔진만 쓴다. 지금 scan 은 로그인만으로 Pro 로 바뀌지 않지만
            # (ci 일 때만), 엔진 선택을 벤더의 기본값에 맡기지 않는다.
            "--oss-only",
            "--timeout",
            self.RULE_TIMEOUT,
            "--timeout-threshold",
            self.TIMEOUT_THRESHOLD,
            "--quiet",
            *[str(t) for t in targets],
        ]
        t0 = time.time()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, encoding="utf-8", errors="replace", env=_env(self.path), timeout=self.timeout
            )
        except subprocess.TimeoutExpired as e:
            # 시간 제한이 없으면 커밋 전 훅과 CI 가 영원히 멈춘다
            raise BackendError(
                f"semgrep 이 {self.timeout}초 안에 끝나지 않았습니다 (대상 {len(targets)}개). "
                f"POLICYPACK_SEMGREP_TIMEOUT 으로 늘릴 수 있습니다."
            ) from e
        finally:
            os.unlink(cfg)
        elapsed = time.time() - t0

        if not proc.stdout.strip():
            raise BackendError(f"semgrep 이 출력을 내지 않았습니다 (종료 코드 {proc.returncode})\n{proc.stderr[:2000]}")
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise BackendError(f"semgrep JSON 을 읽지 못했습니다: {e}\n{proc.stdout[:500]}") from e
        return data, elapsed
