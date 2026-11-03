"""Anthropic Messages API 를 표준 라이브러리로 부른다. SDK 를 설치하지 않아도 판정자·에이전트가 돈다.

재시도: 429·5xx·529·연결 실패·연결 끊김은 10초, 20초 … 로 네 번까지 다시 보낸다.
그 밖의 HTTP 오류는 바로 RuntimeError 다.
목적지: SDK 처럼 `ANTHROPIC_BASE_URL` 이 있으면 그리로 보낸다(사내 게이트웨이). scan 의 알림이 그 목적지를 적는다.
"""

from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable

DEFAULT_BASE = "https://api.anthropic.com"
RETRY = (429, 500, 502, 503, 529)

Transport = Callable[[dict], dict]
"""요청 본문을 받아 Messages API 응답(JSON)을 돌려주는 함수. 시험에서는 가짜를 넣는다."""


def endpoint(env: dict | None = None) -> str:
    base = (os.environ if env is None else env).get("ANTHROPIC_BASE_URL") or DEFAULT_BASE
    return base.rstrip("/") + "/v1/messages"


def http_transport(key: str, timeout: float = 300.0, url: str | None = None, sleep=time.sleep) -> Transport:
    url = url or endpoint()

    def send(body: dict) -> dict:
        for attempt in range(5):
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode(),
                headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")
                if e.code in RETRY and attempt < 4:
                    sleep(10 * (attempt + 1))
                    continue
                raise RuntimeError(f"HTTP {e.code}: {detail[:300]}") from None
            except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
                # 연결 끊김(ConnectionResetError)·응답 중간 끊김(IncompleteRead) 도 다시 보낸다(dev 실측: 끊김 하나가
                # 검사 전체를 내부 오류로 멈췄다)
                if attempt < 4:
                    sleep(10 * (attempt + 1))
                    continue
                raise RuntimeError(f"연결 실패: {e}") from None
        raise RuntimeError("재시도 끝")

    return send
