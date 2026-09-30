"""`claude` CLI 를 단발 판정자로 부른다. API 키가 필요 없다.

## 격리가 이 어댑터의 전부다

판정자는 **프롬프트만 보고** 답해야 한다. 작업 폴더의 파일을 읽거나, 사용자 설정을
물려받거나, 여러 턴을 돌면 그 답은 "이 코드 조각에 대한 판정"이 아니게 된다.
`--allowedTools ""` 만으로는 판정자가 작업 폴더 안의 파일을 읽었다. 그래서 아래를 모두 막는다.
`ISOLATION_FLAGS` 의 해시를 테스트가 핀한다.

  - `--restricted --strict-mcp-config --mcp-config '{"mcpServers":{}}'`
  - `--setting-sources ""` — 사용자·프로젝트 설정을 물려받지 않는다
  - `--max-turns 1`, `--permission-prompts none`
  - 도구 전부를 `--disallowedTools` 로 명시
  - 폴더 이름으로도 프로젝트를 추론하지 못하게 중립적인 빈 임시 폴더에서 실행
  - `MAX_THINKING_TOKENS=0` — 사고 과정 없이 답만

그리고 **답이 왔어도 `num_turns != 1` 이거나 권한 거부가 있었으면 버린다**(`failure="isolation"`).
도구를 쓰려 했다는 뜻이다. 엔진은 실패한 답을 판정자가 없을 때처럼 판정에 넣지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time

from policypack.judge.base import SYSTEM, Answer, Failure, Question, parse_answer

BIN = os.environ.get("POLICYPACK_CLAUDE_BIN", "claude")

#: 이 목록에서 하나라도 빠지면 판정자가 프롬프트 밖을 본다. 테스트가 해시를 핀한다.
ISOLATION_FLAGS: tuple[str, ...] = (
    "--restricted",
    "--strict-mcp-config",
    "--mcp-config",
    '{"mcpServers":{}}',
    "--setting-sources",
    "",
    "--no-session-persistence",
    "--settings",
    "{}",
    "--max-turns",
    "1",
    "--permission-prompts",
    "none",
    "--disallowedTools",
    "Read",
    "Glob",
    "Grep",
    "Bash",
    "Edit",
    "Write",
    "NotebookEdit",
    "WebFetch",
    "WebSearch",
    "Task",
    "TodoWrite",
    "Artifact",
    "Skill",
    "ToolSearch",
    "SendMessage",
    "ReportFindings",
    "ListAgents",
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    "TaskStop",
    "CronList",
    "CronCreate",
    "PushNotification",
    "ScheduleWakeup",
)

ISOLATION_SHA = hashlib.sha256("\0".join(ISOLATION_FLAGS).encode()).hexdigest()[:16]

ALIASES = {"haiku": "haiku", "sonnet": "sonnet", "opus": "opus"}


def build_command(model: str) -> list[str]:
    return [BIN, "-p", "--output-format", "json", "--model", model, *ISOLATION_FLAGS]


def available() -> bool:
    return shutil.which(BIN) is not None


def _remove(folder: str) -> bool:
    """중립 폴더를 지운다. 판정자가 그 안에 무엇을 남겼으면 True 다."""
    try:
        wrote = bool(os.listdir(folder))
    except OSError:
        wrote = True  # 폴더를 지우거나 바꿔 놓았다
    shutil.rmtree(folder, ignore_errors=True)
    return wrote


class ClaudeCliJudge:
    """구독으로 도는 판정자. 호출마다 사용자의 구독 사용량을 쓴다."""

    def __init__(
        self,
        model: str = "haiku",
        system: str | None = SYSTEM,
        timeout: int = 180,
        thinking_tokens: str = "0",
        retries: int = 1,
    ) -> None:
        self.model = ALIASES.get(model, model)
        self.id = f"claude-cli:{model}"
        self.system = system
        self.timeout = timeout
        self.thinking_tokens = thinking_tokens
        self.retries = retries

    def ask(self, q: Question) -> Answer:
        cmd = build_command(self.model)
        if self.system is not None:
            cmd += ["--system-prompt", self.system]
        env = dict(os.environ, MAX_THINKING_TOKENS=self.thinking_tokens)

        proc = None
        for attempt in range(self.retries + 1):
            # 폴더 이름으로도 프로젝트를 추론하지 못하게 중립적인 빈 폴더에서 돈다
            neutral = tempfile.mkdtemp(prefix="judge-")
            try:
                proc = subprocess.run(
                    cmd,
                    input=q.prompt(),
                    capture_output=True,
                    encoding="utf-8",  # 질문에 한글이 있다. 로캘 인코딩(CP949 등)으로 쓰면 깨진다
                    errors="replace",  # 깨진 출력은 아래에서 파싱 실패가 된다. 예외로 검사 전체를 멈추지 않는다
                    timeout=self.timeout,
                    cwd=neutral,
                    env=env,
                )
            except subprocess.TimeoutExpired:
                return self._fail("timeout")
            except OSError:
                # 실행 파일이 없거나 실행할 수 없다. 판정자를 부르지 못한 것이지 도구 오류가 아니다
                return self._fail("transport")
            finally:
                wrote = _remove(neutral)
            if wrote:
                # 작업 폴더에 무엇을 남겼다. 프롬프트에 답만 한 것이 아니다
                return self._fail("isolation")
            if proc.returncode == 0:
                break
            if attempt >= self.retries:
                return self._fail("transport")
            time.sleep(2)

        # 판정자의 출력 모양은 우리가 정하지 못한다. 예상과 다르면 예외가 아니라 파싱 실패다
        try:
            d = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return self._fail("parse")
        if not isinstance(d, dict):
            return self._fail("parse")

        if d.get("is_error"):
            return self._fail("transport")

        # 도구를 쓰려 했거나 여러 턴을 돌았으면 버린다. 스니펫만 보고 답해야 한다.
        if d.get("num_turns") != 1 or d.get("permission_denials"):
            return self._fail("isolation")

        result = d.get("result")
        if result is not None and not isinstance(result, str):
            return self._fail("parse")
        raw, evidence, parse_failed = parse_answer(result or "")
        return Answer(raw=raw, evidence=evidence, failure="parse" if parse_failed else None)

    def _fail(self, kind: Failure) -> Answer:
        return Answer(raw="?", failure=kind)
