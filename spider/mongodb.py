#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"MongoDB storage for crawled news"

import datetime
import urllib.parse


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
        self.collection.create_index(
            [("seq", self.pymongo.ASCENDING)],
            unique=True,
            sparse=True,
            name="uk_news_seq",
        )
        self.collection.create_index(
            [("url", self.pymongo.ASCENDING)],
            unique=True,
            sparse=True,
            name="uk_news_url",
        )
        self.collection.create_index([("title", self.pymongo.ASCENDING)], sparse=True, name="idx_news_title")
        self.collection.create_index([("time", self.pymongo.DESCENDING)], name="idx_news_time")
        self.collection.create_index([("type", self.pymongo.ASCENDING), ("time", self.pymongo.DESCENDING)], name="idx_news_type_time")
        self.collection.create_index([("publisher", self.pymongo.ASCENDING), ("time", self.pymongo.DESCENDING)], name="idx_news_publisher_time")

    def is_exist(self, info):
        query = self._identity_query(info)
        if not query:
            return False
        return self.collection.count_documents(query, limit=1) > 0

    def insert(self, info):
        document = self._normalize_document(info)
        try:
            self.collection.insert_one(document)
            return True
        except self.DuplicateKeyError:
            return False

    def _identity_query(self, info):
        clauses = []
        if info.get("seq"):
            clauses.append({"seq": info.get("seq")})
        if info.get("url"):
            clauses.append({"url": info.get("url")})
        if info.get("title"):
            clauses.append({"title": info.get("title")})
        if len(clauses) == 1:
            return clauses[0]
        if clauses:
            return {"$or": clauses}
        return None

    def _normalize_document(self, info):
        now = datetime.datetime.utcnow()
        document = {
            "publisher": info.get("publisher") or "10jqka",
            "type": info.get("type"),
            "seq": info.get("seq"),
            "url": info.get("url"),
            "title": info.get("title"),
            "content": info.get("content"),
            "time": info.get("time"),
            "source": info.get("source"),
            "summary": info.get("summary"),
            "created_at": now,
            "updated_at": now,
        }
        return {key: value for key, value in document.items() if value is not None}
