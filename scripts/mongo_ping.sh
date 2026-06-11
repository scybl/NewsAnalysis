#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
.venv/bin/python - <<'PY'
import os
from pymongo import MongoClient

uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
client = MongoClient(uri, serverSelectionTimeoutMS=2000)
print(client.admin.command("ping"))
PY
