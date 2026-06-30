# NewsCrawler

独立新闻采集项目。它负责来源发现、正文抓取、标准化、去重、MongoDB 写入和运行记录，不包含新闻分析逻辑。

## 安装

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

## 运行

```bash
news-crawler sources
news-crawler crawl --source tonghuashun --latest --max-pages 1 --dry-run
news-crawler crawl --source guardian --latest --max-pages 1
news-crawler crawl --source politico --latest --max-articles 10 --dry-run
news-crawler crawl --source all --latest
news-crawler crawl --source guardian --since 2026-01-01T00:00:00Z --until 2026-01-31T23:59:59Z
```

Bloomberg 已默认启用；若公开页面触发登录墙或反爬，可配置 `BLOOMBERG_COOKIE` 后运行：

```bash
news-crawler crawl --source bloomberg --latest --max-pages 1
```

Bloomberg 默认优先使用 `https://www.bloomberg.com/lineup-next/api/stories` 获取最新文章 URL，再回抓文章页并解析 `__NEXT_DATA__.props.pageProps.story` 正文；API 不可用时会回退到 `/latest` 页面解析。服务器网络若无法直连 Bloomberg，可配置：

```bash
BLOOMBERG_PROXY=http://user:pass@proxy-host:proxy-port
BLOOMBERG_COOKIE='name=value; another=value'
```

也可以用 `BLOOMBERG_PROXY_FILE` / `BLOOMBERG_COOKIE_FILE` 从文件读取敏感值。安装 `curl-cffi` 可更接近真实 Chrome 请求指纹：

```bash
python -m pip install -e '.[bloomberg]'
```

Docker 镜像中启用该可选依赖：

```bash
NEWS_CRAWLER_INSTALL_BLOOMBERG=1 docker compose up -d --build news-crawler
```

Politico 使用 `rss.politico.com` 的公开 RSS feed，默认分类包括 `politics`、`healthcare` 和 `energy`。如需追加或覆盖分类，可配置：

```bash
POLITICO_FEED_URLS="custom=https://rss.politico.com/example.xml" news-crawler crawl --source politico --categories custom --dry-run
```

单个来源的单次采集默认最多运行 300 秒，超时会写入 `failed`/`timeout` 运行记录。可通过环境变量 `NEWS_CRAWLER_MAX_RUNTIME_SECONDS` 或命令行参数 `--max-runtime-seconds` 调整，传 `0` 表示不限制。

`politico_browser` 是实验性的浏览器 Provider，会用 Selenium/Chrome 直接打开 `https://www.politico.com/news/` 并解析新闻链接。它默认禁用，避免没有浏览器环境的调度任务失败。启用前需安装 browser 依赖并移除禁用项：

```bash
python -m pip install -e '.[browser]'
NEWS_CRAWLER_DISABLED_SOURCES= news-crawler crawl --source politico_browser --latest --max-pages 1 --max-articles 5 --dry-run
```

可选绕过配置：

```bash
# 复用专用 Chrome profile。建议新建专用目录，不要直接用日常 Chrome profile。
POLITICO_BROWSER_HEADLESS=0 \
POLITICO_BROWSER_PROFILE_DIR=/path/to/politico-chrome-profile \
NEWS_CRAWLER_DISABLED_SOURCES= \
news-crawler crawl --source politico_browser --latest --max-pages 1 --max-articles 5 --dry-run

# 使用代理。Chrome 原生代理对带用户名密码的代理支持有限，优先使用无认证代理或已配置认证的 profile。
POLITICO_BROWSER_PROXY=http://host:port \
NEWS_CRAWLER_DISABLED_SOURCES= \
news-crawler crawl --source politico_browser --latest --max-pages 1 --max-articles 5 --dry-run

# 注入 Cookie，支持浏览器导出的 {"cookies":[...]} 或单个/list cookie JSON。
POLITICO_BROWSER_COOKIES_JSON='{"cookies":[{"name":"cf_clearance","value":"...","domain":".politico.com","path":"/"}]}' \
NEWS_CRAWLER_DISABLED_SOURCES= \
news-crawler crawl --source politico_browser --latest --max-pages 1 --max-articles 5 --dry-run
```

如果 Politico 返回 Cloudflare 验证页，`politico_browser` 会失败并记录 blocked/empty discovery 类错误；这种情况下需要可通过验证的 Chrome profile、Cookie/代理，或继续使用 RSS Provider。

服务器 Docker 部署时，需要显式构建浏览器版镜像，并持久化 profile：

```bash
NEWS_CRAWLER_INSTALL_BROWSER=1 \
NEWS_CRAWLER_DISABLED_SOURCES= \
POLITICO_BROWSER_HEADLESS=1 \
POLITICO_BROWSER_PROFILE_DIR=/app/local_data/politico_chrome_profile \
docker compose up -d --build news-crawler
```

如果服务器 IP 被 Cloudflare 挑战，优先加代理：

```bash
NEWS_CRAWLER_INSTALL_BROWSER=1 \
NEWS_CRAWLER_DISABLED_SOURCES= \
POLITICO_BROWSER_PROXY=http://host:port \
docker compose up -d --build news-crawler
```

也可以把本机拿到的 `cf_clearance` 临时放进 `POLITICO_BROWSER_COOKIES_JSON`，但 Cookie 往往绑定 IP/浏览器指纹；从本机复制到服务器可能失效。长期运行更推荐“服务器同一出口 IP + 专用 profile + 代理”。

已有旧 `news.articles` 数据时，可一次性迁移：

```bash
news-crawler migrate-legacy --source-collection articles
```

常驻调度：

```bash
news-crawler schedule --source all --interval 1800 --max-pages 1
```

查询健康状态或取消任务：

```bash
news-crawler health
news-crawler runs --source tonghuashun --limit 20
news-crawler cancel RUN_ID
```

MongoDB 默认写入：

- `news.raw_articles`
- `news.crawl_runs`

NewsAnalysis 只读取 `raw_articles`，不应启动本项目内部脚本。
