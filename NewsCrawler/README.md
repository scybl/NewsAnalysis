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
news-crawler crawl --source all --latest
news-crawler crawl --source guardian --since 2026-01-01T00:00:00Z --until 2026-01-31T23:59:59Z
```

Bloomberg 通常会对匿名 `/latest` 请求返回 403，因此默认在
`NEWS_CRAWLER_DISABLED_SOURCES` 中禁用。配置 `BLOOMBERG_COOKIE` 后移除该项，即可运行：

```bash
news-crawler crawl --source bloomberg --latest --max-pages 1
```

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
