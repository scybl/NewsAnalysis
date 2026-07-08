# 数据与运维

本文记录 NewsAnalysis 当前的数据分层、冷备份、后台治理和数据自查策略。

## 数据分层

| 数据 | 热/冷策略 | 主要位置 |
| --- | --- | --- |
| 股票基础信息 | 热数据 | `stock_data.stock_metadata` |
| 股票资料包 | 热数据 | `stock_data.stock_packages` |
| 日 K 与指标 | 热数据 | `stock_data.stock_dataset_rows` |
| 分时行情 | 冷数据为主，服务器只保留索引和近期缓存 | `market_data.stock_minute_day_index`、`market_data.minute_day_buckets`、百度网盘 |
| 新闻原文 | 热数据 | `news.raw_articles` |
| 新闻运行记录 | 热数据 | `news.crawl_runs`、`news.source_health` |
| 开盘啦结果 | 热数据 | `market_data.kaipanla_results` |

日 K 与股票资料包用于前端快速阅读和分析，保留在服务器 MongoDB。历史分时体积大，按股票和年份写入 JSONL 对象上传到百度网盘；服务器保留覆盖索引、上传状态、缺口状态和最近访问缓存。

## 分时冷备份结构

当前结构：

```text
NewsAnalysis/cold/stock_minute/v1/
  objects_stock_year/
    {source}/
      {ts_code}/
        {year}.jsonl
```

示例：

```text
NewsAnalysis/cold/stock_minute/v1/objects_stock_year/pytdx_history/000001.SZ/2026.jsonl
```

每个文件包含同一股票同一年已确认完整的交易日分时记录。索引集合会记录：

- `source`
- `ts_code`
- `trade_date`
- `storage_object`
- `relative_path`
- `remote_path`
- `sha256`
- `row_count`
- `upload_status`
- `object_trade_year`

读取某一天数据时，系统先查索引；本地缓存不存在或 hash 不匹配时，从百度网盘下载对应年份对象到缓存目录，然后只解析目标交易日，不需要解压整包。

## 缓存策略

分时冷数据下载后进入本地缓存。缓存用于加速重复读取，不作为唯一数据源。上传成功且索引写入后，服务器上的临时归档文件应被清理，只保留必要索引和缓存。

当前设计目标：

- 最近访问数据可快速复用。
- 缓存达到容量上限后按访问时间淘汰。
- 冷备份对象以 sha256 校验，校验失败会删除本地缓存并报错。

## 最新月份策略

完整冷备份建议按月归档。当前月或最新未闭合月份不应提前视作完整冷备份：

1. 日常抓取先写服务器热数据和索引。
2. 当月份闭合、交易日补齐、覆盖检查通过后，再生成冷备份对象。
3. 冷备份上传成功后更新 `upload_status=uploaded`。
4. 前端和后台以索引状态展示该股票的服务器存储、冷备份天数和健康检查结果。

这样可以避免把尚未补满的最新月份当成最终冷数据。

## 股票存储状态

“股票数据 / 股票存储状态”按每只股票展示：

- 热数据行数和资料包数量。
- 日 K 覆盖、最新日期和缺口天数。
- 分时冷备份索引、上传天数、起止日期。
- 最近健康检查时间。
- 健康状态：正常、关注、异常、未知。

页面支持搜索、排序和状态过滤，方便快速定位缺日 K、分时异常或冷备份未完成的股票。

## 数据抽检

系统治理页的数据抽检面向所有关键数据资产：

- 股票日 K 是否有缺口、部分异常或最新交易日未覆盖。
- 分时索引与冷备份上传进度是否一致。
- 新闻源是否有连续失败、解析异常或异常空结果。
- 后台任务是否存在卡死、重启中断或重 IO 冲突。
- 审计日志和运行日志是否能解释最近异常。

空闲时可以运行随机抽检，避免服务器资源长期闲置。抽检结果应写入可查询记录，并在前端展示检查项、检查结果和异常点。

## 审计报告

服务器数据审计脚本会生成 Markdown 报告，统计业务数据和 MongoDB 集合占用。报告示例字段：

| 数据源 | 类型 | 总条 | 服务器存储 | 冷备份条数 | 占据服务器存储 |
| --- | --- | ---: | ---: | ---: | ---: |
| 同花顺新闻 | 新闻数据 | 10000 | 2000 | 8000 | 2 GB |
| 股票日 K | 股票热数据 | 1000000 | 1000000 | 0 | 10 GB |
| 分时行情 | 股票分时 | 2000000 | 10000 | 1990000 | 500 MB |

本地快捷命令可封装为 `chakan`：在服务器生成报告、拉回本机并打开。脚本应打印当前正在分析的数据类型，避免长时间无输出。

## 行情数据

开盘啦功能统一放在“行情数据”页。常用 CLI：

```bash
python -m stock_pipeline kaipanla list
python -m stock_pipeline kaipanla validate
python -m stock_pipeline kaipanla run daily_data --params '{"end_date":"2026-01-16"}'
```

页面会默认展示最新可用交易日数据；如果当天未更新，应回退展示上一个已有交易日，不强行显示空白当日。

## NewsCrawler 边界

NewsCrawler 独立负责新闻采集，NewsAnalysis 只读消费新闻库。NewsAnalysis 不直接抓新闻站点，也不从后台页面启动新闻爬虫。

本地验证新闻源：

```bash
cd NewsCrawler
.venv/bin/news-crawler sources
.venv/bin/news-crawler crawl --source tonghuashun --latest --max-pages 1 --dry-run
.venv/bin/news-crawler crawl --source politico --latest --max-articles 10 --dry-run
```

Guardian、Bloomberg、Politico 等凭据由 NewsCrawler 或后台凭据管理维护。Bloomberg 可能需要 proxy 或 cookie；Politico browser 模式默认禁用。

## Tushare 状态

Tushare 当前封存，不作为新开发默认数据源。不要把 Tushare 作为日 K 补齐、资料包更新、审计基线或新功能前提，除非项目明确重新启用。

本地历史 Tushare 数据可以继续作为兼容输入读取，但新的抓取和补齐优先使用东方财富、AkShare 候选源、腾讯兜底、本地缓存或服务器已有数据。

## 输出目录

默认输出：

```text
reports/{股票代码}_{时间戳}/
  raw/*.json
  dossier.json
  analysis.md
sessions/{股票代码}.json
```

`reports/` 和 `sessions/` 是运行态目录，不应作为源码同步到生产代码包。
