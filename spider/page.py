#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"提取页面文章"

import logging
import random
import re
import time
from urllib.parse import urlparse

import bs4
import requests

import article


headers = {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"}

types = {
    "财经要闻": "today_list",
    "宏观经济": "cjzx_list",
    "产经新闻": "cjkx_list",
    "国际财经": "guojicj_list",
    "金融市场": "jrsc_list",
    "公司新闻": "fssgsxw_list",
    "区域经济": "region_list",
    "财经评论": "fortune_list",
    "财经人物": "cjrw_list",
}


class Fetcher(object):
    def __init__(self, timeout=(5, 20), retries=3, backoff=2.0, session=None):
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.session = session or requests.Session()
        self.session.headers.update(headers)

    def get(self, url):
        last_error = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code == 403:
                    raise requests.HTTPError("403 Forbidden", response=response)
                response.raise_for_status()
                if not response.encoding:
                    response.encoding = response.apparent_encoding
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self.retries:
                    break
                sleep_time = self.backoff ** (attempt - 1) + random.uniform(0.2, 1.0)
                logging.warning("fetch retry %s/%s url=%s error=%s", attempt, self.retries, url, exc)
                time.sleep(sleep_time)
        raise last_error


class Page(object):
    def __init__(self, kind, pn, fetcher=None, article_sleep=(2.0, 5.0)):
        self.__m_url = "http://m.10jqka.com.cn/"
        self.fetcher = fetcher or Fetcher()
        self.article_sleep = article_sleep
        self.type = kind

        if types.get(kind):
            self.url = self.build_url(kind, pn)
            self.__analize_page()
            self.articles = self.__get_all_article()
        else:
            raise ValueError("该分类不存在: " + str(kind))

    @staticmethod
    def build_url(kind, pn):
        return "http://news.10jqka.com.cn/" + types[kind] + "/index_" + str(pn) + ".shtml"

    def __analize_page(self):
        response = self.fetcher.get(self.url)
        self.__soup = bs4.BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)

    def __normalize_article_url(self, url):
        parsed = urlparse(url)
        if parsed.netloc.endswith("10jqka.com.cn"):
            return re.sub(r"https?://\w+\.10jqka\.com\.cn/", self.__m_url, url)
        return url

    def __get_article_links(self):
        links = []
        seen = set()
        for node in self.__soup.select(".arc-title > a"):
            href = node.get("href")
            if not href:
                continue
            url = self.__normalize_article_url(href)
            if url in seen:
                continue
            seen.add(url)
            links.append(url)
        return links

    def __get_all_article(self):
        articles = []
        for link in self.__get_article_links():
            try:
                response = self.fetcher.get(link)
                articles.append(article.Article(self.type, response.content, response.encoding, url=response.url))
            except (IndexError, KeyError, ValueError, TypeError, requests.RequestException) as exc:
                logging.warning("parse article failed kind=%s url=%s error=%s", self.type, link, exc)
            finally:
                time.sleep(random.uniform(*self.article_sleep))
        return articles

    def get_articles(self):
        return self.articles
