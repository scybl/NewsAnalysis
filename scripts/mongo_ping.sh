#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
export PROJECT_ROOT="$(pwd)"
.venv/bin/python - <<'PY'
import os
import urllib.parse
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

from stock_pipeline.secret_store import secret_value

load_dotenv(Path(os.environ["PROJECT_ROOT"]) / ".env")
uri = secret_value("mongo.uri", ("MONGODB_URI", "MONGO_URI"))
if not uri:
    host = os.getenv("MONGO_HOST", "localhost")
    port = int(os.getenv("MONGO_PORT", "27017"))
    user = secret_value("mongo.user", ("MONGO_USER",))
    password = secret_value("mongo.password", ("MONGO_PASSWORD",))
    auth_source = os.getenv("MONGO_AUTHSOURCE", "admin")
    if user and password:
        uri = f"mongodb://{urllib.parse.quote_plus(user)}:{urllib.parse.quote_plus(password)}@{host}:{port}/?authSource={auth_source}"
    else:
        uri = f"mongodb://{host}:{port}/"
client = MongoClient(uri, serverSelectionTimeoutMS=2000)
print(client.admin.command("ping"))
PY
