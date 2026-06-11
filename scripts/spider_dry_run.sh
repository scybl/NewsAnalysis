#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
exec .venv/bin/python spider/main.py \
  --types "${SPIDER_TYPES:-财经要闻}" \
  --max-pages "${SPIDER_MAX_PAGES:-1}" \
  --threads "${SPIDER_THREADS:-1}" \
  --article-sleep "${SPIDER_ARTICLE_SLEEP:-0,0}" \
  --page-sleep "${SPIDER_PAGE_SLEEP:-0,0}" \
  --dry-run \
  --log-file "${SPIDER_LOG_FILE:-/tmp/newsanalysis-spider-dryrun.log}"
