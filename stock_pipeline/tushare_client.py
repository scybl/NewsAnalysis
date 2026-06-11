from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class TushareError(RuntimeError):
    pass


@dataclass
class TushareResult:
    api_name: str
    fields: list[str]
    records: list[dict[str, Any]]


class TushareClient:
    def __init__(self, token: str, base_url: str = "http://api.tushare.pro", timeout: int = 60, pause: float = 0.22):
        self.token = token
        self.base_url = base_url
        self.timeout = timeout
        self.pause = pause

    def query(self, api_name: str, params: dict[str, Any] | None = None, fields: str = "") -> TushareResult:
        payload = {
            "api_name": api_name,
            "token": self.token,
            "params": params or {},
            "fields": fields,
        }
        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise TushareError(f"{api_name} 网络请求失败：{exc}") from exc
        finally:
            if self.pause:
                time.sleep(self.pause)

        parsed = json.loads(body)
        if parsed.get("code") != 0:
            raise TushareError(f"{api_name} 返回错误 code={parsed.get('code')} msg={parsed.get('msg')}")

        data = parsed.get("data") or {}
        result_fields = data.get("fields") or []
        items = data.get("items") or []
        records = [dict(zip(result_fields, item)) for item in items]
        return TushareResult(api_name=api_name, fields=result_fields, records=records)
