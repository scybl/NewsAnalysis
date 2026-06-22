#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"MongoDB configuration"

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stock_pipeline.secret_store import secret_value


load_dotenv(PROJECT_ROOT / ".env")

config = {
    "uri": secret_value("mongo.uri", ("MONGODB_URI", "MONGO_URI")),
    "host": os.getenv("MONGO_HOST", "localhost"),
    "port": int(os.getenv("MONGO_PORT", "27017")),
    "username": secret_value("mongo.user", ("MONGO_USER",)),
    "password": secret_value("mongo.password", ("MONGO_PASSWORD",)),
    "auth_source": os.getenv("MONGO_AUTHSOURCE", "admin"),
    "database_name": os.getenv("MONGODB_DATABASE", "news"),
    "collection_name": os.getenv("MONGODB_COLLECTION", "articles"),
    "server_selection_timeout_ms": int(os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "8000")),
    "socket_timeout_ms": int(os.getenv("MONGO_SOCKET_TIMEOUT_MS", "8000")),
}
