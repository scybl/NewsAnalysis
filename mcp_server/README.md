# ValueScope DataHub MCP server

This package is a thin MCP wrapper over the ValueScope DataHub gateway. REST remains the source of truth and all authorization stays server-side.

Status in ValueScope DataHub `2.0.x`: the historical Agent Gateway remains a paused integration surface. The MCP package is retained under the historical `newsanalysis-mcp` package name for local development and future re-enable work, but the Web app does not currently issue `na_agent_...` tokens and protected `/api/agent/v1` calls return unavailable until `AGENT_GATEWAY_AVAILABLE` is explicitly restored.

## Install

```bash
cd mcp_server
python -m pip install -e .
```

## Configure

When the Agent Gateway is re-enabled, create an `R,B` token from **Admin Console -> Agent Gateway**, then set:

```bash
export NEWSANALYSIS_BASE_URL=http://127.0.0.1:8765
export NEWSANALYSIS_AGENT_TOKEN=na_agent_xxx
newsanalysis-mcp
```

`NEWSANALYSIS_*` and `newsanalysis-mcp` are compatibility names from the historical engineering name.

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
