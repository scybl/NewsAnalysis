from __future__ import annotations

import hashlib
import json
import random
import urllib.parse
import urllib.request
from dataclasses import dataclass


BAIDU_TRANSLATE_ENDPOINT = "https://fanyi-api.baidu.com/api/trans/vip/translate"
MAX_BAIDU_TEXT_CHARS = 4500


class TranslationError(RuntimeError):
    pass


@dataclass(frozen=True)
class BaiduTranslateConfig:
    app_id: str
    secret_key: str
    endpoint: str = BAIDU_TRANSLATE_ENDPOINT


class BaiduTranslateClient:
    def __init__(self, config: BaiduTranslateConfig, *, timeout: float = 20):
        self.config = config
        self.timeout = timeout

    def translate(self, text: str, *, source: str = "en", target: str = "zh") -> str:
        source_text = str(text or "").strip()
        if not source_text:
            return ""
        return "\n\n".join(
            self._translate_part(part, source=source, target=target)
            for part in _split_text(source_text, MAX_BAIDU_TEXT_CHARS)
        )

    def _translate_part(self, text: str, *, source: str, target: str) -> str:
        salt = str(random.randint(32768, 65536))
        sign = hashlib.md5((self.config.app_id + text + salt + self.config.secret_key).encode("utf-8")).hexdigest()
        payload = urllib.parse.urlencode(
            {
                "q": text,
                "from": source,
                "to": target,
                "appid": self.config.app_id,
                "salt": salt,
                "sign": sign,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.config.endpoint,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # network and JSON errors should surface as one admin-facing failure
            raise TranslationError(f"百度翻译请求失败：{exc}") from exc

        if data.get("error_code"):
            raise TranslationError(f"百度翻译失败：{data.get('error_msg') or data.get('error_code')}")
        rows = data.get("trans_result") or []
        translated = "\n".join(str(row.get("dst") or "") for row in rows if row.get("dst"))
        if not translated:
            raise TranslationError("百度翻译没有返回译文。")
        return translated


def _split_text(text: str, limit: int) -> list[str]:
    value = str(text or "").strip()
    if len(value) <= limit:
        return [value] if value else []
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in value.splitlines():
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > limit:
            if current:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
            chunks.extend(paragraph[index : index + limit] for index in range(0, len(paragraph), limit))
            continue
        next_len = current_len + len(paragraph) + (1 if current else 0)
        if current and next_len > limit:
            chunks.append("\n".join(current))
            current = [paragraph]
            current_len = len(paragraph)
        else:
            current.append(paragraph)
            current_len = next_len
    if current:
        chunks.append("\n".join(current))
    return chunks
