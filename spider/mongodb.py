#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"MongoDB storage for crawled news"

import urllib.parse

from news_schema import dedupe_filter, ensure_news_indexes, normalize_news_document


class MongoNewsStore(object):
    def __init__(self, config):
        import pymongo
        from pymongo.errors import DuplicateKeyError

        self.pymongo = pymongo
        self.DuplicateKeyError = DuplicateKeyError
        self.config = config
        self.client = pymongo.MongoClient(
            self._connection_uri(),
            serverSelectionTimeoutMS=config.get("server_selection_timeout_ms", 8000),
            socketTimeoutMS=config.get("socket_timeout_ms", 8000),
        )
        self.db = self.client[config["database_name"]]
        self.collection = self.db[config["collection_name"]]
        self.client.admin.command("ping")

    def _connection_uri(self):
        uri = self.config.get("uri")
        if uri:
            return uri

        username = self.config.get("username")
        password = self.config.get("password")
        auth_source = self.config.get("auth_source", "admin")
        host = self.config.get("host", "localhost")
        port = self.config.get("port", 27017)

        if username and password:
            user = urllib.parse.quote_plus(username)
            passwd = urllib.parse.quote_plus(password)
            return "mongodb://{}:{}@{}:{}/?authSource={}".format(user, passwd, host, port, auth_source)
        return "mongodb://{}:{}/".format(host, port)

    def close(self):
        if self.client:
            self.client.close()
            self.client = None

    def ensure_schema(self):
        ensure_news_indexes(self.collection, self.pymongo)

    def is_exist(self, info):
        query = self._identity_query(info)
        if not query:
            return False
        return self.collection.count_documents(query, limit=1) > 0

    def is_existing_identity(self, seq=None, url=None, title=None):
        return self.is_exist({"seq": seq, "url": url, "title": title})

    def insert(self, info):
        document = self._normalize_document(info)
        try:
            self.collection.insert_one(document)
            return True
        except self.DuplicateKeyError:
            return False

    def _identity_query(self, info):
        return dedupe_filter(self._normalize_document(info))

    def _normalize_document(self, info):
        return normalize_news_document(info, publisher_default="10jqka", source_name="10jqka")
