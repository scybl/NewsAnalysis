# NewsCrawler 与 NewsAnalysis 项目分离计划

## 1. 决策

现有工程拆分为两个职责独立、可以分别安装和部署的项目：

```text
NewsCrawler                         NewsAnalysis
可靠地带回新闻                     理解和使用新闻

来源发现与正文抓取                 新闻检索与清洗
重试、限速与反爬处理               实体、股票和行业关联
标准化与保守去重                   聚类、摘要、情感与影响分析
采集任务与来源健康状态             Agent、报告、搜索与展示
写入 raw_articles                  读取 raw_articles，写入分析结果
```

项目之间不共享 Python 包，不互相导入内部代码，也不直接启动对方脚本。双方只通过版本化新闻文档契约和 MongoDB collection 通信。

本次分离首先解决新闻爬虫。行情、财务、龙虎榜和其他市场数据不纳入 NewsCrawler。

---

## 当前实施状态（2026-06-25）

计划内工程任务已经完成：

- 在当前工作区建立可独立安装、测试和构建的 `NewsCrawler/` 项目。
- NewsCrawler 拥有独立 `pyproject.toml`、配置、CLI、Dockerfile、Compose、契约和测试。
- 已实现公共模型、Provider 协议、Registry、Pipeline、Executor、DedupeService、Repository、运行记录模型和 HealthProjector。
- 已迁移同花顺、Guardian 和 Bloomberg 为正式 Provider。
- 新数据写入 `news.raw_articles`，运行记录写入 `news.crawl_runs`。
- 支持来源并行、来源内限速、结构化重试、跨进程取消、运行查询和失败隔离。
- Bloomberg 使用持久化 checkpoint 保存未完成 URL，可在中断后恢复。
- `HealthProjector` 会根据运行记录更新 `news.source_health`。
- 提供常驻 `schedule` 命令以及 `runs`、`health`、`cancel` 运维命令。
- 提供 `migrate-legacy` 命令，将旧 `news.articles` 一次性迁移到 `raw_articles`。
- NewsAnalysis 已增加只读 `MongoRawNewsRepository`，新闻库、股票新闻证据和 Agent 上下文通过该边界读取。
- NewsAnalysis 已删除内部新闻采集 CLI、旧 MySQL 新闻链路和已被替代的爬虫源码。
- NewsAnalysis Web 不再启动同花顺或 Guardian 新闻爬虫；原进程控制目前只保留非新闻的分钟行情补采。
- NewsAnalysis 管理端提供 NewsCrawler 只读采集状态面板，展示 `source_health` 与近期 `crawl_runs`，但不反向启动或控制爬虫。
- NewsAnalysis 管理端将“新闻采集”作为独立只读运维页面，不与新闻库、股票资料或其他数据源控制混排；页面明确展示数据所有权、运行事实、来源健康和错误详情。
- 原 `/api/admin/spider/*` 已改为明确的 `/api/admin/market-fetch/*`。
- 两份 `news.v1` JSON Schema 完全一致，并有契约测试。
- NewsAnalysis 已实现 `latest`、`get_by_article_id`、`list_unprocessed` 和独立消费状态记录。
- 根 Compose 已编排 MongoDB、NewsCrawler 和 NewsAnalysis Web 三个服务。
- CI 会运行两个项目的测试并构建两个镜像，部署流程会检查两个服务健康。
- 三个来源均有固定离线 fixture；完整测试、独立目录测试、Compose 校验、镜像构建和临时 MongoDB 集成测试均已通过。
- 原 `spider/` 目录、旧日志、缓存、重复依赖和 legacy Bloomberg 脚本已清理。

`NewsCrawler/` 已是安装、测试、镜像和部署均独立的项目目录。是否把它发布到另一个远程 Git 仓库属于版本库托管选择，不影响本计划的架构和运行验收。

---

## 2. 项目边界

### 2.1 NewsCrawler

NewsCrawler 负责：

- 同花顺、Guardian、Bloomberg 等新闻源适配
- 文章发现、正文获取和来源特有解析
- 请求超时、重试、限速、取消和失败隔离
- 新闻文档标准化
- 生成去重键并执行保守去重策略
- MongoDB `raw_articles` 写入
- 采集运行记录、日志、指标和来源健康状态
- 独立 CLI、配置、依赖、测试和 Docker 镜像

NewsCrawler 不负责：

- 股票行情和财务数据
- 新闻摘要、情感分析、事件聚类和投资判断
- Agent 与分析报告
- NewsAnalysis 用户、权限和页面
- 直接修改 NewsAnalysis 数据

### 2.2 NewsAnalysis

NewsAnalysis 负责：

- 从 `raw_articles` 查询新闻
- 对新闻进行清洗、丰富和分析
- 关联公司、股票、行业和宏观主题
- 生成摘要、事件、情感、影响判断和证据上下文
- 分析结果、Agent、报告、搜索和展示
- 记录自身消费状态与分析产物

NewsAnalysis 不负责：

- 新闻网站请求和 HTML 解析
- Selenium、浏览器 Cookie 和代理
- 新闻源翻页、重试、限速和反爬
- 启动或停止 NewsCrawler 内部脚本
- 判断某个新闻源如何抓取

---

## 3. 项目通信

第一阶段采用共享 MongoDB、分 collection 的方式：

```text
NewsCrawler
    ↓ owns / writes
news.raw_articles
news.crawl_runs
news.source_health

NewsAnalysis
    ↓ reads
news.raw_articles
    ↓ owns / writes
news.analysis_documents
news.analysis_jobs
```

所有权规则：

- `raw_articles` 由 NewsCrawler 写入，NewsAnalysis 只读。
- `crawl_runs` 和 `source_health` 仅属于 NewsCrawler。
- `analysis_documents` 和 `analysis_jobs` 仅属于 NewsAnalysis。
- 不允许两个项目共同修改同一业务文档。

当前不引入 Kafka、RabbitMQ、Redis Queue 或微服务框架。只有在共享 MongoDB 的轮询或查询成为可测量瓶颈后，才评估消息队列。

---

## 4. 版本化数据契约

两个项目共享的是文档规范，不是代码。

`raw_articles` 的最低契约：

```json
{
  "schema_version": "news.v1",
  "article_id": "stable-id",
  "source_name": "guardian",
  "external_id": "source-id",
  "url": "https://example.com/article",
  "canonical_url": "https://example.com/article",
  "title": "Article title",
  "summary": "Optional source summary",
  "content": "Normalized plain text",
  "published_at": "2026-06-25T10:30:00Z",
  "fetched_at": "2026-06-25T10:35:00Z",
  "section": "business",
  "language": "en",
  "author": "Author",
  "tags": [],
  "content_hash": "sha256",
  "title_time_hash": "sha256",
  "raw_metadata": {}
}
```

契约规则：

- `schema_version` 必填。
- `article_id` 在重跑和 upsert 后保持稳定。
- 时间保存为 UTC ISO 8601；读取端兼容迁移期旧字符串时间。
- 正文保存为纯文本，来源原始字段放入 `raw_metadata`。
- 新增可选字段不提升主版本；删除字段或改变语义时发布新 schema。
- NewsAnalysis 遇到不支持的主版本时必须明确报错，不能静默误读。

契约在两个项目中各保存一份 JSON Schema，并通过契约测试保证一致；不建立共享运行时代码包。

---

## 5. NewsCrawler 架构

### 5.1 目录

```text
NewsCrawler/
├── pyproject.toml
├── README.md
├── Dockerfile
├── .env.sample
├── contracts/
│   └── raw-article.news.v1.schema.json
├── src/news_crawler/
│   ├── cli.py
│   ├── config.py
│   ├── models.py
│   ├── provider.py
│   ├── registry.py
│   ├── source_config.py
│   ├── pipeline.py
│   ├── executor.py
│   ├── dedupe.py
│   ├── repository.py
│   ├── mongo_repository.py
│   ├── runs.py
│   ├── health.py
│   ├── observer.py
│   └── providers/
│       ├── tonghuashun.py
│       ├── guardian.py
│       └── bloomberg.py
└── tests/
    ├── fixtures/
    ├── test_contract.py
    ├── test_dedupe.py
    ├── test_pipeline.py
    └── test_providers.py
```

### 5.2 依赖关系

```text
CLI / Scheduler
    ↓
CrawlPipeline          创建采集计划，拆分来源任务
    ↓
TaskExecutor           执行、重试、限速、取消
    ↓
NewsProvider           来源发现与解析
    ↓
DedupeService          生成去重键，执行重复判断策略
    ↓
NewsRepository         upsert 与查询边界
    └── MongoNewsRepository
```

旁路记录：

```text
TaskExecutor → CrawlRunRepository → HealthProjector
TaskExecutor → RunObserver        → 日志与指标
```

### 5.3 Provider 协议

```python
class NewsProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities

    def discover(self, request: NewsCrawlRequest) -> Iterable[ArticleRef]:
        ...

    def fetch(self, ref: ArticleRef) -> NewsArticle:
        ...
```

Provider 只实现来源特有发现和解析，不负责数据库、任务状态、Web API 或健康统计。

### 5.4 去重与 Repository

`DedupeService` 负责：

- canonical URL
- 内容哈希
- 标题与日期哈希
- 去重键优先级
- 重复命中原因

`NewsRepository` 负责：

```python
find_existing_by_keys()
upsert_article()
```

Repository 隔离 MongoDB API，但不决定业务去重规则。当前只实现 `MongoNewsRepository`，不为假设中的存储后端预建结构。

### 5.5 运行记录和健康状态

每次来源任务写入不可变的 `CrawlRunRecord`，包含：

- 请求范围和来源
- started、finished、cancelled 或 failed 状态
- discovered、fetched、inserted、updated、skipped、failed
- timeout、duplicate、parser_error、blocked 等结构化 metrics
- warnings 和 errors

`HealthProjector` 根据近期运行记录生成健康状态。健康状态是可重建投影，不是唯一事实来源。

第一阶段使用同步 `RunObserver` 输出日志和指标，不建设事件总线。

---

## 6. NewsAnalysis 输入边界

NewsAnalysis 保留独立的读取层：

```python
class RawNewsRepository:
    def search(...): ...
    def latest(...): ...
    def get_by_article_id(...): ...
    def list_unprocessed(...): ...
```

其 MongoDB 实现只读取 `raw_articles`。分析代码、Agent 和 Web 页面不直接出现 `pymongo.collection` 查询细节。

分析消费状态不得写回 `raw_articles`。需要记录处理进度时，使用 NewsAnalysis 自己拥有的 collection：

```text
analysis_documents
analysis_ingestion_state
```

---

## 7. 迁移阶段

### 阶段 0：基线与保护

- 保存三个来源的最小 HTML/JSON 测试样本。
- 记录当前字段完整率、抓取数量和重复率。
- 为现有标准化、canonical URL 和去重逻辑补离线测试。
- 备份 MongoDB 索引与文档样本。

完成标准：

- 不访问外网也能验证解析结果。
- 可以比较迁移前后的文档。

### 阶段 1：建立独立 NewsCrawler 项目

- 创建独立 `pyproject.toml`、配置、CLI、测试和 Dockerfile。
- 配置只读取自身环境变量或 secret file，不导入 NewsAnalysis 的密钥库。
- 建立 `news.v1` JSON Schema。
- 实现模型、DedupeService、Repository 和公共 Pipeline。

完成标准：

- NewsCrawler 可以独立安装。
- NewsCrawler 的测试不需要把 NewsAnalysis 加入 `PYTHONPATH`。
- FakeProvider 可以跑通发现、抓取、去重和写入。

### 阶段 2：迁移同花顺

- 将现有同花顺列表和正文解析迁入 `TonghuashunProvider`。
- 保持旧文档读取兼容，并将新文档写入 `raw_articles`。
- 旧 `spider/main.py` 入口停止使用。

完成标准：

- dry-run 和 MongoDB 写入均可运行。
- 关键字段完整率不低于旧实现。
- 同花顺只有一个正式运行入口。

### 阶段 3：迁移 Guardian

- 将 API 查询和响应解析迁入 `GuardianProvider`。
- 移除其独立 MongoDB、日志、调度和结果 JSON。
- 定时任务改为调用 NewsCrawler CLI。

完成标准：

- Guardian 代码不依赖 NewsAnalysis。
- 运行统计进入 `crawl_runs`。

### 阶段 4：迁移 Bloomberg

- 把 URL 发现与正文抓取封装为一个 Provider。
- 用明确 checkpoint 保存待抓 URL、状态和重试次数。
- 移除散落 JSON、重复 requirements 和平台专属运行入口。

完成标准：

- 用户只启动一次 Bloomberg 采集任务。
- 中断后能够恢复未完成 URL。

### 阶段 5：切换 NewsAnalysis

- 增加 `RawNewsRepository`。
- 将新闻搜索、Agent 新闻证据和新闻库页面切换到 `raw_articles`。
- NewsAnalysis 删除新闻爬虫 CLI。
- NewsAnalysis Web 删除新闻爬虫进程控制 API 和页面入口。
- 分钟行情等非新闻能力不得随新闻爬虫一起误删。

完成标准：

- NewsAnalysis 启动和测试不要求 NewsCrawler 源码存在。
- NewsAnalysis 不导入任何 NewsCrawler 模块。
- 删除 NewsCrawler 目录后，NewsAnalysis 仍可读取已采集新闻。

### 阶段 6：物理清理

- 从 NewsAnalysis 删除 `spider/`。
- 删除旧 MySQL 新闻采集链路。
- 删除爬虫专用脚本、依赖、日志配置和文档。
- 更新 Compose，使 NewsCrawler 和 NewsAnalysis 成为两个容器。
- 可选：将 NewsCrawler 目录迁移到独立 Git 仓库。

完成标准：

- 两个项目分别安装、测试和构建。
- 不存在双向源码依赖。
- 不存在两套正式新闻爬虫入口。
- 被替代代码及时删除，删除量大于新增胶水代码量。

---

## 8. 部署

初始部署保持简单：

```text
docker compose
├── mongo
├── news-crawler
└── news-analysis
```

- 两个应用使用不同镜像和依赖。
- MongoDB 凭据可以来自同一部署 secret，但权限应逐步收紧。
- NewsCrawler 只需要写 raw/crawl collections。
- NewsAnalysis 只读 raw collection，并读写 analysis collections。
- 两个应用分别拥有健康检查和日志。

---

## 9. 测试

NewsCrawler 必须覆盖：

- 新闻契约
- 各来源固定样本解析
- URL 与时间标准化
- 去重键和重复策略
- MongoDB upsert
- 超时、重试、取消和失败隔离
- checkpoint 恢复
- CrawlRunRecord 与 HealthProjector

NewsAnalysis 必须覆盖：

- `news.v1` 兼容读取
- 不支持 schema 主版本时明确失败
- 新闻搜索和时间范围
- Agent 新闻证据构建
- 分析消费状态不修改 raw 文档

实时网站抓取只作为手动集成测试，不能成为 CI 成功的前提。

---

## 10. 验收标准

### 独立性

- 两个项目拥有独立依赖、配置、CLI、测试和 Dockerfile。
- 任一项目均不导入另一项目的源码。
- NewsAnalysis 不启动 NewsCrawler 进程。
- NewsCrawler 不读取 NewsAnalysis 的密钥库或本地数据目录。

### 数据边界

- `raw_articles` 只有 NewsCrawler 写入。
- `analysis_documents` 只有 NewsAnalysis 写入。
- 双方通过 `news.v1` 契约通信。
- 数据契约具备自动化测试。

### 可维护性

- 新增新闻源只需要实现 Provider 和样本测试。
- Provider 不包含数据库和调度代码。
- MongoDB API 不泄漏到 Pipeline 和分析业务代码。
- 旧入口、重复 requirements 和独立调度脚本被删除。

### 运行

- 单个来源失败不影响其他来源。
- 采集任务可查询、取消和追溯。
- NewsAnalysis 在 NewsCrawler 停止时仍可分析已有新闻。
- 两个容器可以分别重启和升级。

### 前端适配

- 后台导航提供独立“新闻采集”入口。
- 不可用或调试中的模块统一排在后台导航末尾，避免打断主要运维路径。
- 开盘啦作为数据源在“数据源”页统一配置、调度和查看记录，不占用独立后台一级模块。
- 行情补采复用股票搜索索引，支持股票代码、名称、全拼和首字母缩写检索，并在启动任务前解析为标准 `ts_code`。
- 新闻采集页只读取 `crawl_runs`、`source_health` 和 collection 名称，不提供启动、停止、取消或修改 NewsCrawler 的操作。
- 页面明确表达 `NewsCrawler → raw_articles → NewsAnalysis` 的单向所有权边界。
- 来源健康展示成功率、连续失败、最近成功/失败、最近新增和平均耗时。
- 近期运行表格字段与 `CrawlResult` 一一对应，至少展示状态、起止时间、耗时、发现、获取、新增、更新、跳过和失败。
- 运行错误、警告、指标和 `run_id` 可以从表格进入详情查看。
- NewsCrawler 不可达或尚未产生运行记录时，页面显示可理解的空状态，不伪装成正常运行。

---

## 11. 架构原则

1. 爬虫负责获取，分析项目负责理解。
2. 项目通过数据契约通信，不共享内部代码。
3. 一个 collection 只有一个写入所有者。
4. Provider 不负责存储、调度、Web API 或健康统计。
5. Pipeline 不解析 HTML，也不直接调用 MongoDB。
6. DedupeService 决定去重策略，Repository 只提供查询和持久化边界。
7. Registry 只维护 Provider 名称到实现的映射。
8. Health 是运行记录的投影，运行记录才是事实。
9. 删除旧代码优先于增加抽象。
10. 抽象必须解决已经存在的重复，不预测不确定的未来需求。
11. 优先组合而非继承，接口保持窄小。
12. 所有公共能力和来源解析必须能够离线测试。
13. 共享基础设施不意味着抹平来源差异。
14. 先完成可独立运行的简单系统，再依据真实瓶颈引入队列或分布式组件。
