from __future__ import annotations

import json
import re
from typing import Any

import bs4


def extract_seq_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"[cm](\d+)", url)
    return match.group(1) if match else None


class Article:
    def __init__(self, kind: str, text: bytes, encoding: str | None, url: str | None = None):
        self._soup = bs4.BeautifulSoup(text, "lxml", from_encoding=encoding)
        self._text = self._soup.decode()
        self._detail = self._get_detail_content()

        self.type = kind
        self.url = self.get_url(url)
        self.seq = self.get_seq()
        self.title = self.get_title()
        self.content = self.get_content()
        self.time = self.get_time()
        self.source = self.get_source()
        self.summary = self.get_summary()

    def _get_detail_content(self) -> dict[str, Any]:
        detail = self._extract_json_after("detailContent:")
        return detail or {}

    def _extract_json_after(self, marker: str) -> dict[str, Any] | None:
        start = self._text.find(marker)
        if start < 0:
            return None

        start = self._text.find("{", start)
        if start < 0:
            return None

        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(self._text)):
            char = self._text[i]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
            else:
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            parsed = json.loads(self._text[start : i + 1])
                        except ValueError:
                            return None
                        return parsed if isinstance(parsed, dict) else None
        return None

    def _get_full_ctime(self) -> str | None:
        match = re.search(r"ctime:\s*'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})'", self._text)
        return match.group(1) if match else None

    def _canonical_url(self) -> str | None:
        canonical = self._soup.find("link", rel="canonical")
        if canonical:
            value = canonical.get("href")
            return str(value) if value else None
        return None

    def get_url(self, fallback: str | None = None) -> str | None:
        value = self._detail.get("url") or self._canonical_url() or fallback
        return str(value) if value else None

    def get_seq(self) -> str | None:
        seq = self._detail.get("seq")
        if seq:
            return str(seq)

        for value in (self.url, self._canonical_url()):
            seq = extract_seq_from_url(value)
            if seq:
                return seq
        return None

    def get_time(self) -> str:
        full_ctime = self._get_full_ctime()
        if full_ctime:
            return full_ctime

        ctime = self._detail.get("ctime")
        if ctime:
            ctime = str(ctime)
            if re.match(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", ctime):
                return ctime
            if re.match(r"\d{2}-\d{2}\s+\d{2}:\d{2}", ctime):
                canonical = self._canonical_url()
                year = re.search(r"/(\d{4})/", canonical if canonical else "")
                if year:
                    return year.group(1) + "-" + ctime + ":00"

        date = self._soup.select(".date")
        if date:
            match = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", date[0].text.replace("\xa0", ""))
            if match:
                return match.group(1)
        raise ValueError("article time not found")

    def get_title(self) -> str:
        title = self._detail.get("title")
        if title:
            return str(title).strip()

        dom_title = self._soup.select("#articleTitle")
        if dom_title:
            return dom_title[0].text.strip()
        raise ValueError("article title not found")

    def get_content(self) -> str:
        content = self._detail.get("content")
        if content:
            return bs4.BeautifulSoup(str(content), "lxml").get_text("\n", strip=True).replace("\u3000", "").strip()

        dom_content = self._soup.select(".page_content")
        if dom_content:
            return dom_content[0].text.replace("\u3000", "").strip()
        raise ValueError("article content not found")

    def get_source(self) -> str | None:
        source = self._detail.get("source")
        if source:
            return str(source).strip()
        source_dom = self._soup.select(".source")
        if source_dom:
            return source_dom[0].text.strip()
        return None

    def get_summary(self) -> str | None:
        summary = self._detail.get("summ")
        if summary:
            return bs4.BeautifulSoup(str(summary), "lxml").get_text("", strip=True).replace("\u3000", "").strip()
        description = self._soup.find("meta", attrs={"name": "description"})
        if description:
            value = description.get("content")
            return str(value) if value else None
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "seq": self.seq,
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "time": self.time,
            "source": self.source,
            "summary": self.summary,
        }

    def get_info_dict(self) -> dict[str, Any]:
        return self.to_dict()
