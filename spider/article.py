#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"提取文章信息"

import json
import re

import bs4


def extract_seq_from_url(url):
    if not url:
        return None
    match = re.search(r"[cm](\d+)", url)
    if match:
        return match.group(1)
    return None


class Article(object):
    def __init__(self, kind, text, encoding, url=None):
        self.__soup = bs4.BeautifulSoup(text, "lxml", from_encoding=encoding)
        self.__text = self.__soup.decode()
        self.__detail = self.__get_detail_content()

        self.type = kind
        self.url = self.get_url(url)
        self.seq = self.get_seq()
        self.title = self.get_title()
        self.content = self.get_content()
        self.time = self.get_time()
        self.source = self.get_source()
        self.summary = self.get_summary()

    def __get_detail_content(self):
        detail = self.__extract_json_after("detailContent:")
        if detail:
            return detail
        return {}

    def __extract_json_after(self, marker):
        start = self.__text.find(marker)
        if start < 0:
            return None

        start = self.__text.find("{", start)
        if start < 0:
            return None

        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(self.__text)):
            char = self.__text[i]
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
                            return json.loads(self.__text[start:i + 1])
                        except ValueError:
                            return None
        return None

    def __get_full_ctime(self):
        match = re.search(r"ctime:\s*'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})'", self.__text)
        if match:
            return match.group(1)
        return None

    def __canonical_url(self):
        canonical = self.__soup.find("link", rel="canonical")
        if canonical:
            return canonical.get("href")
        return None

    def get_url(self, fallback=None):
        return self.__detail.get("url") or self.__canonical_url() or fallback

    def get_seq(self):
        seq = self.__detail.get("seq")
        if seq:
            return str(seq)

        for value in (self.url, self.__canonical_url()):
            seq = extract_seq_from_url(value)
            if seq:
                return seq
        return None

    def get_time(self):
        full_ctime = self.__get_full_ctime()
        if full_ctime:
            return full_ctime

        ctime = self.__detail.get("ctime")
        if ctime:
            ctime = str(ctime)
            if re.match(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", ctime):
                return ctime
            if re.match(r"\d{2}-\d{2}\s+\d{2}:\d{2}", ctime):
                canonical = self.__canonical_url()
                year = re.search(r"/(\d{4})/", canonical if canonical else "")
                if year:
                    return year.group(1) + "-" + ctime + ":00"

        date = self.__soup.select(".date")
        if date:
            match = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", date[0].text.replace("\xa0", ""))
            if match:
                return match.group(1)
        raise ValueError("article time not found")

    def get_title(self):
        title = self.__detail.get("title")
        if title:
            return title.strip()

        dom_title = self.__soup.select("#articleTitle")
        if dom_title:
            return dom_title[0].text.strip()
        raise ValueError("article title not found")

    def get_content(self):
        content = self.__detail.get("content")
        if content:
            return bs4.BeautifulSoup(content, "lxml").get_text("\n", strip=True).replace("\u3000", "").strip()

        dom_content = self.__soup.select(".page_content")
        if dom_content:
            return dom_content[0].text.replace("\u3000", "").strip()
        raise ValueError("article content not found")

    def get_source(self):
        source = self.__detail.get("source")
        if source:
            return source.strip()
        source_dom = self.__soup.select(".source")
        if source_dom:
            return source_dom[0].text.strip()
        return None

    def get_summary(self):
        summary = self.__detail.get("summ")
        if summary:
            return bs4.BeautifulSoup(summary, "lxml").get_text("", strip=True).replace("\u3000", "").strip()
        description = self.__soup.find("meta", attrs={"name": "description"})
        if description:
            return description.get("content")
        return None

    def get_info_dict(self):
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
