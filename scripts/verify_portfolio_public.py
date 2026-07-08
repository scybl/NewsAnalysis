from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORTFOLIO_ROOT = ROOT / "portfolio_public"

ALLOWED_SUFFIXES = {
    "",
    ".css",
    ".html",
    ".json",
    ".md",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".webp",
}

FORBIDDEN_FILENAMES = {
    ".env",
    ".deploy.env",
    "docker-compose.yml",
    "docker-compose.prod.yml",
    "Dockerfile",
    "id_rsa",
    "id_ed25519",
}

FORBIDDEN_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "cache",
    "local_data",
    "logs",
    "reports",
    "sessions",
    "node_modules",
    "out_repo",
}

FORBIDDEN_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"\b(?:access|refresh|secret|sign|app)[_-]?token\b\s*[:=]", re.IGNORECASE),
    re.compile(r"\b(?:secret|sign|app)[_-]?key\b\s*[:=]", re.IGNORECASE),
    re.compile(r"\bpassword\b\s*[:=]", re.IGNORECASE),
    re.compile(r"\bMONGODB_URI\b|\bMONGO_PASSWORD\b", re.IGNORECASE),
    re.compile(r"\b106\.54\.27\.114\b"),
    re.compile(r"/opt/NewsAnalysis"),
    re.compile(r"/home/ubuntu"),
    re.compile(r"pan\.baidu\.com/rest/2\.0", re.IGNORECASE),
]


def scan(root: Path) -> list[str]:
    findings: list[str] = []
    if not root.exists():
        return [f"missing portfolio directory: {root}"]
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        parts = set(rel.parts)
        if parts & FORBIDDEN_PARTS:
            findings.append(f"forbidden path segment: {rel}")
            continue
        if path.is_dir():
            continue
        if path.name in FORBIDDEN_FILENAMES:
            findings.append(f"forbidden filename: {rel}")
        if path.suffix not in ALLOWED_SUFFIXES:
            findings.append(f"forbidden file type: {rel}")
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".svg", ".webp"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(f"non-utf8 text file: {rel}")
            continue
        for pattern in FORBIDDEN_PATTERNS:
            if pattern.search(text):
                findings.append(f"forbidden content pattern {pattern.pattern!r}: {rel}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify that portfolio_public is safe to publish.")
    parser.add_argument("path", nargs="?", default=str(DEFAULT_PORTFOLIO_ROOT), help="Portfolio directory to scan.")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    findings = scan(root)
    if findings:
        print("Portfolio public safety check failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print(f"Portfolio public safety check passed: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
