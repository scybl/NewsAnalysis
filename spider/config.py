#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"MongoDB configuration"

import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

config = {
    "uri": os.getenv("MONGODB_URI"),
    "host": os.getenv("MONGO_HOST", "localhost"),
    "port": int(os.getenv("MONGO_PORT", "27017")),
    "username": os.getenv("MONGO_USER", ""),
    "password": os.getenv("MONGO_PASSWORD", ""),
    "auth_source": os.getenv("MONGO_AUTHSOURCE", "admin"),
    "database_name": os.getenv("MONGODB_DATABASE", "news"),
    "collection_name": os.getenv("MONGODB_COLLECTION", "articles"),
    "server_selection_timeout_ms": int(os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "8000")),
    "socket_timeout_ms": int(os.getenv("MONGO_SOCKET_TIMEOUT_MS", "8000")),
}
