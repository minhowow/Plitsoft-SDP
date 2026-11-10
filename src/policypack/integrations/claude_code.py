"""Claude Code 의 PostToolUse 훅.

Claude Code 가 파일을 고칠 때마다(Edit·Write) 그 파일 하나를 정적 조건으로만 검사한다. AI 를 부르지
않고 아무것도 밖으로 보내지 않는다. 훅은 편집마다 돌아서 빨라야 하고, 코드를 이미 Claude 에게 보낸 사람이라도
다른 서비스로 보내는 것은 따로 동의할 일이다.

    .claude/settings.json
    {"hooks": {"PostToolUse": [{"matcher": "Edit|Write",
        "hooks": [{"type": "command", "command": "policypack hook claude-code", "timeout": 60}]}]}}

Claude Code 는 stdin 으로 `{"tool_name", "tool_input": {"file_path"}, "cwd", ...}` 를 준다. 결과는 이렇게 돌려준다.

- 확실한 '검토 필요'가 있으면 stdout 에 `{"decision": "block", "reason": ..., "systemMessage": ...}` 을 내고 0 으로
  끝난다. Claude Code 는 `reason` 을 Claude 에게, `systemMessage` 한 줄을 사용자에게 보여 준다. 편집은 이미 됐다 —
  막는 것이 아니라 Claude 가 경고를 읽고 이어 가게 한다.
- '불확실'만 있으면 알리지 않는다. 정적 조건만 쓰면 AI 에게 물을 곳이 모두 '불확실'로 남아 편집마다 끼어든다.
- JS/TS 가 아니거나 생성물(node_modules·dist·축소 번들 등)이면 검사하지 않고 0 으로 끝난다.
- 검사하지 못하면 `systemMessage` 로 사용자에게만 알리고 0 으로 끝난다. Claude 의 편집은 이어 간다.
"""

from __future__ import annotations

import io
import json
import sys
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

TOOLS = frozenset({"Edit", "Write"})

REASON_HEAD = (
    "policypack(국내 법·정책 검토)이 방금 고친 파일에서 법·정책상 검토가 필요한 지점을 찾았습니다. "
    "코드로 해결할 수 있으면 고치고, 사업상 판단이 필요하면(동의를 받는지, 국외 이전 근거가 있는지 등) "
    "사용자에게 아래 질문을 전하세요. 이 도구는 법률 자문이 아닙니다."
)


def target(payload: dict) -> Path | None:
    """검사할 파일. 훅이 볼 일이 아니면 None."""
    if payload.get("tool_name") not in TOOLS:
        return None
    raw = (payload.get("tool_input") or {}).get("file_path")
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = Path(payload.get("cwd") or ".") / path
    return path


def admitted(path: Path) -> bool:
    """전체 검사가 고를 파일인지(확장자, 생성물 디렉터리, 축소 번들, 크기, 인코딩). 이름을 댄 파일은 scan 이
    거르지 않으므로 여기서 거른다."""
    from policypack import gitscope
    from policypack.discover import admit, extensions_for
    from policypack.errors import ConfigError
    from policypack.static.compile import LANGUAGE_GLOBS

    try:
        root = gitscope.repo_root(path.parent)
    except ConfigError:
        root = path.parent
    return admit(path, root, extensions_for(list(LANGUAGE_GLOBS))) == "ok"


def run(stdin: str, config: str | None, scan: Callable[[list[str]], int]) -> int:
    try:
        payload = json.loads(stdin or "{}")
    except json.JSONDecodeError as e:
        print(f"policypack 훅: stdin 이 JSON 이 아닙니다({e})", file=sys.stderr)
        return 1
    path = target(payload) if isinstance(payload, dict) else None
    if path is None or not path.exists() or not admitted(path):
        return 0

    argv = ["scan", str(path), "--output-format", "concise", "--no-color", "--fail-on", "review"]
    if config:
        argv += ["--config", config]
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = scan(argv)
    if code == 0:
        return 0
    if code != 1:
        why = err.getvalue().strip().splitlines()
        note = f"policypack 훅: {path.name} 을 검사하지 못했습니다(종료 코드 {code}). {why[-1] if why else ''}".strip()
        print(json.dumps({"systemMessage": note}, ensure_ascii=False))
        return 0
    report = out.getvalue().strip()
    n = sum(1 for line in report.splitlines() if "  검토 필요  " in line)
    print(
        json.dumps(
            {
                "decision": "block",
                "reason": f"{REASON_HEAD}\n\n{report}",
                "systemMessage": f"policypack: {path.name} 에 법·정책 검토 필요 {n}건 — Claude 에게 전했습니다",
            },
            ensure_ascii=False,
        )
    )
    return 0
