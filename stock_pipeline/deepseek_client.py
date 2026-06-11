from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Iterable


class DeepSeekError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com", model: str = "deepseek-v4-pro", timeout: int = 180):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(self, messages: list[dict[str, str]], stream: bool = False) -> str:
        if stream:
            chunks = []
            for chunk in self.chat_stream(messages):
                print(chunk, end="", flush=True)
                chunks.append(chunk)
            print()
            return "".join(chunks)

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "reasoning_effort": "high",
            "thinking": {"type": "enabled"},
        }
        parsed = self._post_json(payload)
        try:
            return parsed["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DeepSeekError(f"DeepSeek 响应格式异常：{parsed}") from exc

    def chat_stream(self, messages: list[dict[str, str]]) -> Iterable[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "reasoning_effort": "high",
            "thinking": {"type": "enabled"},
        }
        request = self._request(payload)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    parsed = json.loads(data)
                    delta = parsed.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content
        except urllib.error.URLError as exc:
            raise DeepSeekError(f"DeepSeek 流式请求失败：{exc}") from exc

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = self._request(payload)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise DeepSeekError(f"DeepSeek HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise DeepSeekError(f"DeepSeek 请求失败：{exc}") from exc
        return json.loads(body)

    def _request(self, payload: dict[str, Any]) -> urllib.request.Request:
        return urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
