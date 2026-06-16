#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
export PROJECT_ROOT="$(pwd)"
.venv/bin/python - <<'PY'
import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(os.environ["PROJECT_ROOT"]) / ".env")
uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
client = MongoClient(uri, serverSelectionTimeoutMS=2000)
print(client.admin.command("ping"))
PY
