"""Anthropic API 를 판정자로 쓴다. `ANTHROPIC_API_KEY` 가 필요하다.

CLI 어댑터와 **같은 프롬프트, 같은 시스템 메시지**를 쓴다. 어느 경로로 물어도 같은 질문이다.
CLI 판정자는 키가 필요 없지만 `claude` 가 깔려 있어야 하고 입력에 CLI 가 기본으로 붙이는 내용이 함께 들어간다.
이쪽은 우리가 보낸 것만 들어간다.

`temperature=0` 으로 보낸다. 같은 질문에 같은 답이 나올 확률을 높인다(보장되지는 않는다). 5.5 세대 모델은
temperature 를 받지 않아(400, 2026-11-03 실측) 그 모델에는 빼고 다시 보낸다.
SDK 없이 표준 라이브러리로 부른다(judge/http.py).
"""

from __future__ import annotations

import os

from policypack.judge.base import SYSTEM, Answer, Failure, OncePerRun, Question, parse_answer
from policypack.judge.http import Transport, Unavailable, http_transport

#: 별칭 → 모델 id. 결과를 다시 만들어야 하는 실행에는 전체 id 를 쓴다.
MODELS = {
    "haiku": "claude-haiku-5-5",
    "sonnet": "claude-sonnet-5-5",
    "opus": "claude-opus-5-5",
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
        transport: Transport | None = None,
    ) -> None:
        self.model_id = MODELS.get(model, model)
        # 보고서의 run.judge 에는 별칭이 아니라 실제로 부른 모델 id 를 싣는다(별칭이 가리키는 모델은 바뀔 수 있다)
        self.id = f"anthropic:{self.model_id}"
        self.system = system
        self.timeout = timeout
        self.max_tokens = max_tokens
        self._key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._send = transport
        self._temperature = True
        self.usage: dict[str, int] = {}
        """보낸 질문들의 토큰 사용량 합. 보고서 run.judge_usage 에 싣는다(비용 비교용)."""

    def _connect(self) -> Transport:
        if self._send is None:
            if not self._key:
                raise RuntimeError("ANTHROPIC_API_KEY 가 없습니다. claude-cli 판정자를 쓰거나 키를 설정하세요.")
            self._send = http_transport(self._key, timeout=self.timeout)
        return self._send

    def ask(self, q: Question) -> Answer:
        try:
            send = self._connect()
        except RuntimeError:
            return self._fail("transport")
        body = {
            "model": self.model_id,
            "max_tokens": self.max_tokens,
            "system": self.system,
            "messages": [{"role": "user", "content": q.prompt()}],
        }
        for _ in range(2):
            if self._temperature:
                body["temperature"] = 0
            else:
                body.pop("temperature", None)
            try:
                msg = send(body)
                break
            except Unavailable as e:
                text = str(e)
                timed_out = "시간 초과" in text or "timed out" in text.lower()
                return Answer(raw="?", failure="timeout" if timed_out else "transport", unreachable=True)
            except RuntimeError as e:
                text = str(e)
                if self._temperature and "temperature" in text:
                    self._temperature = False  # 이 모델은 temperature 를 받지 않는다
                    continue
                return self._fail("timeout" if "timed out" in text.lower() else "transport")
        else:
            return self._fail("transport")

        for k, v in (msg.get("usage") or {}).items():
            if isinstance(v, int):
                self.usage[k] = self.usage.get(k, 0) + v
        text = "".join(b.get("text", "") for b in msg.get("content") or [] if b.get("type") == "text")
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
    if kind == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY 가 없습니다. 키를 설정하거나 claude-cli 판정자를 쓰세요"
    return None
