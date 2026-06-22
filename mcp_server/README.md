# NewsAnalysis MCP server

This package is a thin MCP wrapper over the NewsAnalysis Agent Gateway. REST remains the source of truth and all authorization stays server-side.

## Install

```bash
cd mcp_server
python -m pip install -e .
```

## Configure

Create an `R,B` token from **Admin Console -> Agent Gateway**, then set:

```bash
export NEWSANALYSIS_BASE_URL=http://127.0.0.1:8765
export NEWSANALYSIS_AGENT_TOKEN=na_agent_xxx
newsanalysis-mcp
```

Never use an admin password, browser cookie, DeepSeek key, or Tushare key in the MCP config.

## Tools

- `check_health`
- `whoami`
- `search_stocks`
- `get_stock_status`
- `get_stock_data`
- `list_jobs`
- `get_job`
- `wait_for_job`
- `submit_analysis_job`

The MCP server intentionally does not expose credential storage, user administration, crawler control, or dynamic external data fetching.
