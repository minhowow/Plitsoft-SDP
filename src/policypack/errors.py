"""종료 코드와 도구 오류.

종료 코드 규약은 ESLint·Ruff·Semgrep 을 따른다.
  0  검토 필요 없음
  1  검토 필요가 하나 이상
  2  도구 오류 (설정 오류, 백엔드 없음, 팩 스키마 위반 등)

"검토 필요"와 "도구가 고장남"을 가르는 것이 핵심이다. CI 에서 전자는 사람이 볼 일이고
후자는 파이프라인이 멈출 일이다.
"""

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2


class PolicypackError(Exception):
    """사용자에게 보여 줄 도구 오류. 종료 코드 2로 나간다."""

    exit_code = EXIT_ERROR


class PackError(PolicypackError):
    """정책 팩을 읽거나 검증하지 못했다."""


class BackendError(PolicypackError):
    """정적 백엔드(semgrep)를 찾지 못했거나 실행이 실패했다."""


class ConfigError(PolicypackError):
    """설정 파일이나 명령줄 인자가 잘못됐다."""
