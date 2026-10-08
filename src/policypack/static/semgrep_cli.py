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
import math
import os
import re
import shutil
import site
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path

from policypack.errors import BackendError
from policypack.static.backend import PredicateKey, StaticResult
from policypack.static.compile import ANCHOR_ROLE, LANGUAGE_GLOBS, REGION_MARKER
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
    # 사용자 스킴은 사용자 site 가 켜져 있을 때만 이 환경의 것이다. venv 안에서도 넣으면 ~/.local/bin 의 다른
    # semgrep 을 '이 환경에 설치된 판'이라고 적었다(끝까지 점검에서 실측)
    for scheme in (None, f"{os.name}_user") if site.ENABLE_USER_SITE else (None,):
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
        # 절대 경로로 둔다. semgrep 은 대상 폴더에서 돌므로 상대 경로면 다른 파일(검사하는 트리 안의 bin/semgrep
        # 등)을 부른다. resolve 가 아니라 abspath 다 — 링크의 폴더가 PATH 앞에 붙어야 한다
        p = Path(os.path.abspath(override))
        if not p.exists():
            raise BackendError(f"{ENV_VAR} 가 가리키는 파일이 없습니다: {p}")
        if not p.is_file() or not os.access(p, os.X_OK):
            raise BackendError(f"{ENV_VAR} 가 실행할 수 있는 파일이 아닙니다: {p}")
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
        return Path(os.path.abspath(found)), "PATH", notes

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
            # semgrep 의 임시 파일(대상 목록·규칙)도 우리 상태 디렉터리에 둔다. 신호로 끊기면 semgrep 이 지우지
            # 못하고 사용자 임시 폴더에 남았다(실측). 상태 디렉터리는 끝날 때 통째로 지운다
            "TMPDIR": str(state),
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
            stdin=subprocess.DEVNULL,
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
    try:
        version = engine_id(path)
    except BackendError as e:
        # 실행 파일은 있는데 판본을 말하지 못한다(깨진 설치). 진단은 끝까지 낸다
        return {"path": str(path), "version": None, "source": source, "notes": [*notes, str(e)]}
    if not version.startswith(EXPECTED_VERSION):
        notes.append(
            f"버전이 {version} 입니다. policypack 은 {EXPECTED_VERSION}.x 로 시험했습니다. "
            f"엔진 판이 다르면 같은 팩의 판정이 달라질 수 있습니다."
        )
    return {"path": str(path), "version": version, "source": source, "notes": notes}


def timeout_from_env() -> float:
    raw = os.environ.get("POLICYPACK_SEMGREP_TIMEOUT")
    if not raw:  # 비어 있으면 없는 것이다(CI 의 설정 안 된 변수)
        return float(SemgrepBackend.DEFAULT_TIMEOUT)
    try:
        t = float(raw)
    except ValueError:
        t = math.nan
    if not math.isfinite(t) or t <= 0:
        raise BackendError(f"POLICYPACK_SEMGREP_TIMEOUT 은 0보다 큰 초 단위 숫자여야 합니다: {raw!r}")
    return t


def region_targets(rules: list[dict], result: StaticResult, targets: list[Path]) -> list[Path]:
    """함수 경계가 필요한 대상. 함수 단위 규칙의 판정 위치(anchor-on) 조건이 맞았고, 그 규칙의 다른 적용 조건이
    하나도 '거짓'이 아닌 파일이다. '거짓'은 평가기와 같은 기준으로 본다(engine.static_value): 매치가 없고, 그
    조건이 시간 초과로 끊기지 않았고, 파싱이 안 된 파일이라면 정규식 조건(generic 사본이 있는 것)일 때.

    엔진이 끝내지 못한 파일도 같은 기준으로 고른다. 그런 파일에서 매치가 없는 조건은 '모름'이지만 맞은 조건은
    그대로 참이라, 파일 단위로 두면 다른 함수의 가드가 이 발송의 경고를 푼다(검토에서 실측).
    고르지 않은 파일은 함수 경계가 없어 파일 단위로 판정된다. 표지가 없는 설정이면 전부 고른다."""
    groups: dict[tuple[str, str], dict[str, set[PredicateKey]]] = {}
    regex_only: set[PredicateKey] = set()
    for r in rules:
        meta = (r.get("metadata") or {}).get("policypack")
        if not isinstance(meta, dict) or not all(k in meta for k in ("policy", "rule", "group", "predicate")):
            continue
        key = PredicateKey(meta["policy"], meta["rule"], meta["group"], meta["predicate"])
        if meta.get("generic"):
            regex_only.add(key)
        if meta.get(ANCHOR_ROLE) in ("on", "with"):
            groups.setdefault((meta["policy"], meta["rule"]), {"on": set(), "with": set()})[meta[ANCHOR_ROLE]].add(key)
    if not groups:
        return list(targets)
    index = result.index()
    unreliable = result.unreliable_paths()

    def not_false(key: PredicateKey, path: Path) -> bool:
        if path in index.get(key, {}) or result.unfinished(key, path):
            return True
        return path in unreliable and key not in regex_only

    need: set[Path] = set()
    for roles in groups.values():
        anchored = {p for k in roles["on"] for p in index.get(k, {})}
        need |= {p for p in anchored if all(not_false(k, p) for k in roles["with"])}
    return [t for t in targets if t.resolve() in need]


class SemgrepBackend:
    name = "semgrep"

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            path, _, _ = resolve()
            if path is None:
                raise BackendError("semgrep 을 찾지 못했습니다. " + REINSTALL_HINT)
        self.path = path
        self._version: str | None = None
        self.timeout = timeout_from_env()

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

        함수 경계 규칙이 있으면 두 번에 나눠 돈다. 먼저 정책 조건만 모든 대상에 돌리고, 함수 단위 규칙이 걸릴 수
        있는 파일에서만 함수 경계를 구한다. 경계 규칙은 모든 함수에 맞으므로 한 번에 돌리면 광고 발송이 없는
        파일까지 값을 치른다. 실측: 보통 코드에서 2~3배, 한 줄로 축소된 파일에서 수십 배 느렸고, 함수가 수천 개인
        파일은 매치 상한을 넘겨 정책 조건의 매치까지 버려졌다.
        """
        rules = config.get("rules", [])
        region = [r for r in rules if isinstance((r.get("metadata") or {}).get(REGION_MARKER), dict)]
        if not region:
            return self._run_chunks(config, targets)
        result = self._run_chunks({**config, "rules": [r for r in rules if r not in region]}, targets)
        need = region_targets(rules, result, targets)
        # 고르느라 만든 캐시는 버린다. 결과를 받은 쪽이 매치를 고치면(시험이 그런다) 낡은 캐시가 남는다
        result._index = result._unreliable = result._unfinished = None
        if need:
            extra = self._run_chunks({**config, "rules": region}, need)
            # 함수 경계를 가져온다. 파싱 오류는 첫 실행이 이미 적었다. 이 실행에서만 나는 실패(경계 규칙의 시간
            # 초과·매치 상한, 건너뛴 파일, 어느 파일인지 모르는 오류)는 따로 적는다 — 정책 조건의 값은 그대로이고
            # 그 파일의 함수 경계만 없다. 평가기는 그런 파일의 함수 단위 규칙을 '충족'으로 풀지 않는다
            result.regions.update(extra.regions)
            result.rule_errors.extend(extra.rule_errors)
            result.unlocated_errors.extend(extra.unlocated_errors)
            result.regions_failed |= extra.incomplete | set(extra.rule_timeouts)
            result.runs += extra.runs
            result.elapsed_s += extra.elapsed_s
        return result

    def run_all_rules(self, config: dict, targets: list[Path]) -> StaticResult:
        """설정의 규칙을 나누지 않고 전부 엔진에 넘긴다. 규칙을 엔진이 받는지 볼 때 쓴다(validate) — `run` 은
        함수 단위 규칙이 걸리는 파일이 없으면 함수 경계 규칙을 엔진에 넘기지 않는다."""
        return self._run_chunks(config, targets)

    def _run_chunks(self, config: dict, targets: list[Path]) -> StaticResult:
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
        # 규칙의 언어에 드는 대상을 엔진이 오류 없이 건너뛰었다면 그 '매치 없음'은 거짓이 아니다. 어떤 규칙의 언어도
        # 아닌 파일(이름을 댄 deploy.sh 등)은 볼 규칙이 없어 건너뛴 것이라 세지 않는다
        exts = {
            g.lstrip("*")
            for r in config.get("rules", [])
            for lang in r.get("languages", [])
            for g in LANGUAGE_GLOBS.get(lang, [])
        }
        scanned = {Path(p).resolve() for p in (data.get("paths") or {}).get("scanned", [])}
        result.incomplete |= {t for t in targets if t.suffix in exts and t.resolve() not in scanned}
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
        # 대상은 절대 경로로 넘기고 그 공통 조상 폴더에서 돌린다. 대상이 실행 위치 밖이면 semgrep 이 대상마다 따로
        # 파일 찾기를 해 5~7배 느렸다(끝까지 점검에서 실측). 이름을 댄 파일은 .gitignore·test 폴더와 무관하게 검사한다
        abs_targets = [os.path.abspath(t) for t in targets]
        try:
            common = os.path.commonpath(abs_targets) if abs_targets else None
        except ValueError:  # 윈도에서 드라이브가 다르다
            common = None
        run_dir = common if common is None or os.path.isdir(common) else os.path.dirname(common)
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
            # 여기부터는 대상이다. 없으면 '-' 로 시작하는 파일 이름이 옵션이 된다(실측: `--json-output=index.ts`
            # 라는 파일이 있으면 semgrep 이 index.ts 를 결과 JSON 으로 덮어썼고, `-x.ts` 하나로 검사 전체가 실패했다)
            "--",
            *abs_targets,
        ]
        t0 = time.time()
        try:
            # 표준 입력은 막는다. 터미널 입력을 기다리며 멈추지 않게 한다
            proc = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                env=_env(self.path),
                timeout=self.timeout,
                cwd=run_dir,
            )
        except OSError as e:
            raise BackendError(f"semgrep 을 실행하지 못했습니다({self.path}): {e.strerror or e}") from e
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
        if not (
            isinstance(data, dict)
            and isinstance(data.get("results", []), list)
            and isinstance(data.get("errors", []), list)
        ):
            raise BackendError(f"semgrep 출력 형식이 예상과 다릅니다: {proc.stdout[:300]}")
        return data, elapsed
