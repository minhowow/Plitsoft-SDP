"""Anthropic API 를 판정자로 쓴다. `ANTHROPIC_API_KEY` 가 필요하다.

CLI 어댑터와 **같은 프롬프트, 같은 시스템 메시지**를 쓴다. 어느 경로로 물어도 같은 질문이다.
CLI 판정자는 키가 필요 없지만 `claude` 가 깔려 있어야 하고 입력에 CLI 가 기본으로 붙이는 내용이 함께 들어간다.
이쪽은 우리가 보낸 것만 들어간다.

`temperature=0` 으로 둔다. 같은 질문에 같은 답이 나올 확률을 최대한 높인다(보장되지는 않는다).
"""

from __future__ import annotations

import os

from policypack.judge.base import SYSTEM, Answer, Failure, OncePerRun, Question, parse_answer

#: 별칭 → 모델 id.
MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-5",
    "opus": "claude-opus-5",
}

MAX_TOKENS = 512
"""닫힌 질문에 JSON 한 줄로 답하면 된다. 길게 답할 이유가 없다."""


class AnthropicApiJudge:
    def __init__(
        self,
        model: str = "haiku",
        system: str = SYSTEM,
        timeout: float = 120.0,
        max_tokens: int = MAX_TOKENS,
        api_key: str | None = None,
    ) -> None:
        self.model_id = MODELS.get(model, model)
        self.id = f"anthropic:{model}"
        self.system = system
        self.timeout = timeout
        self.max_tokens = max_tokens
        self._key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = None

    def _connect(self):
        if self._client is not None:
            return self._client
        if not self._key:
            raise RuntimeError("ANTHROPIC_API_KEY 가 없습니다. claude-cli 판정자를 쓰거나 키를 설정하세요.")
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover - 설치 여부에 달림
            raise RuntimeError("anthropic 패키지가 없습니다. `uv sync --all-extras` 로 설치하세요.") from e
        self._client = anthropic.Anthropic(api_key=self._key, timeout=self.timeout)
        return self._client

    def ask(self, q: Question) -> Answer:
        try:
            client = self._connect()
        except RuntimeError:
            return self._fail("transport")

        try:
            msg = client.messages.create(
                model=self.model_id,
                max_tokens=self.max_tokens,
                temperature=0,
                system=self.system,
                messages=[{"role": "user", "content": q.prompt()}],
            )
        except Exception as e:  # noqa: BLE001 - SDK 예외 종류가 많다
            return self._fail("timeout" if "timeout" in type(e).__name__.lower() else "transport")

        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        raw, evidence, parse_failed = parse_answer(text)
        return Answer(raw=raw, evidence=evidence, failure="parse" if parse_failed else None)

    def _fail(self, kind: Failure) -> Answer:
        return Answer(raw="?", failure=kind)


def build(spec: str) -> OncePerRun:
    """`--judge` 문자열을 판정자로 바꾼다(claude-cli:haiku · anthropic:sonnet). `none` 은 부르는 쪽이 거른다.

    한 실행 안에서 같은 프롬프트를 두 번 보내지 않게 OncePerRun 으로 감싼다.
    """
    from policypack.judge.claude_cli import ClaudeCliJudge

    if ":" in spec:
        kind, model = spec.split(":", 1)
    else:
        kind, model = spec, "haiku"
    if not model:
        raise ValueError(f"모델 이름이 없습니다: {spec}")
    if kind == "claude-cli":
        return OncePerRun(ClaudeCliJudge(model=model))
    if kind == "anthropic":
        return OncePerRun(AnthropicApiJudge(model=model))
    raise ValueError(f"모르는 판정자: {spec}")


def preflight(spec: str) -> str | None:
    """판정자를 쓸 수 있는지 미리 본다. 쓸 수 없으면 까닭을, 쓸 수 있으면 None 을 돌려준다.

    판정자는 실패를 답으로 내려서 검사를 멈추지 않는다. 그런데 실행 파일이나 키가 아예 없으면 모든 질문이
    까닭 없이 '판정자를 부르지 못했습니다'로 남는다. 그런 설정 문제는 시작할 때 알린다."""
    kind = spec.split(":", 1)[0]
    if kind == "claude-cli":
        from policypack.judge import claude_cli

        if not claude_cli.available():
            return (
                f"claude 실행 파일을 찾지 못했습니다({claude_cli.BIN}). "
                "설치하거나 POLICYPACK_CLAUDE_BIN 에 경로를 주세요"
            )
    if kind == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return "ANTHROPIC_API_KEY 가 없습니다. 키를 설정하거나 claude-cli 판정자를 쓰세요"
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return "anthropic 패키지가 없습니다. `uv sync --extra api` 로 설치하세요"
    return None
