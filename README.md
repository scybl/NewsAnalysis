# ValueScope DataHub

一个面向 ValueScope 分析的数据采集、治理和展示平台。项目把股票资料包、日 K / 分钟行情、财经新闻采集、冷热分层存储、数据质量检查、后台任务调度、权限隔离和数据展示组合成一个可部署、可运维的 Web 工程；采集和整理后的数据用于下游 ValueScope 分析。

> 历史工程名为 `NewsAnalysis`。当前对外产品名统一为 `ValueScope DataHub`；`ValueScope` 分析是下游消费方。代码包名、服务器路径、MCP 包名和部分冷备份路径暂时保留历史命名，避免影响部署和兼容性。

当前版本：`2.0.0`

## 核心能力

- 股票数据：维护股票基础信息、资料包、日 K 与指标、分时覆盖索引，以及每只股票的存储健康状态。
- 冷热分层：日 K 和股票资料包作为服务器热数据；历史分时按股票和年份归档到百度网盘，按需下载到本地缓存后读取。
- 新闻采集：`NewsCrawler/` 是独立采集服务，写入标准化 `news.v1` 文档；DataHub 只读展示新闻库和采集健康状态，并把新闻数据供给 ValueScope 分析。
- 行情数据：集成开盘啦功能、全市场股票列表刷新、市场纵览和交易日维度行情记录。
- 系统治理：后台集中展示任务状态、数据抽检、审计日志、重 IO 保护、冷备份进度和数据资产统计。
- 访问安全：支持注册用户、只读账号、归档账号、邀请码、管理员 TOTP、Fernet 加密密钥库和系统凭据管理。
- 分析供给：保留 DeepSeek / 多 Agent 兼容入口、历史报告读取和数据导出能力，但本仓库的主职责是收集、治理和展示数据。

## 技术栈

| 层级 | 技术 | 用途 |
| --- | --- | --- |
| 后端 | Python 3、`ThreadingHTTPServer`、CLI | Web API、后台任务、数据同步、运维命令 |
| 存储 | MongoDB 7、PyMongo、JSON/JSONL、本地缓存、百度网盘 | 热数据查询、运行态缓存、分时冷备份 |
| 数据源 | 东方财富、开盘啦、同花顺、pytdx/mootdx/tdxpy、Guardian、Bloomberg、Politico | 股票、行情、新闻采集 |
| 前端 | 原生 HTML/CSS/JavaScript、Tailwind 构建 | 管理后台、数据控制台、任务与健康展示 |
| 部署 | Docker Compose、GitHub Actions、bdpan CLI、Prometheus 可选 | 生产部署、CI、冷备份同步、健康检查 |
| 安全 | Fernet、TOTP、签名 Cookie、角色权限 | 密钥隔离、二次验证、后台操作保护 |
| 测试 | pytest、API smoke、集成测试、前端静态契约、回归测试 | 防止接口、页面、数据治理和部署脚本回归 |

> Tushare 当前处于封存状态：项目保留历史本地数据读取和必要兼容入口，但新的数据抓取、审计基线和补齐流程不再默认依赖 Tushare。

## 快速开始

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -r requirements.txt
```

首次运行先把敏感信息写入本地加密密钥库，不要写入 `.env`：

```bash
.venv/bin/python -m stock_pipeline secrets set web.admin_username
.venv/bin/python -m stock_pipeline secrets set web.admin_password
.venv/bin/python -m stock_pipeline secrets set web.session_secret
.venv/bin/python -m stock_pipeline secrets set mongo.password
```

可选启用管理员 Authenticator/TOTP：

```bash
.venv/bin/python -m stock_pipeline secrets setup-admin-totp
```

启动本地 Web：

```bash
scripts/run_web.sh
```

打开 `http://127.0.0.1:8765`。股票可以用代码、名称、首字母或拼音检索，例如 `000001`、`平安银行`、`mygf`。

常用 CLI：

```bash
.venv/bin/python -m stock_pipeline collect 000001
.venv/bin/python -m stock_pipeline analyze 000001.SZ
.venv/bin/python -m stock_pipeline chat 000001.SZ
.venv/bin/python -m stock_pipeline news search 牧原股份
```

只读展示账号：

```text
账号：admin_view
密码：admin_view
```

只读账号可以查看系统治理、股票数据、行情数据、新闻数据、采集状态和任务记录，但不能触发抓取、保存、删除、生成分析或修改账号。

## 后台页面

| 页面 | 作用 |
| --- | --- |
| 访问与安全 | 用户、邀请码、归档账号、系统凭据和二次验证 |
| 系统治理 | 运维状态、数据抽检、审计日志、重 IO 任务和异常摘要 |
| 股票数据 | 股票来源、资料包、日 K、分时覆盖、每只股票存储状态 |
| 行情数据 | 开盘啦功能、市场纵览、全市场列表和定时刷新 |
| 新闻数据 | NewsCrawler 来源健康、采集运行、新闻库只读检索 |

系统级 DeepSeek、Guardian、Bloomberg、Politico、百度网盘等凭据建议在“访问与安全 / 凭据管理”维护。页面只展示安全摘要，不回显密钥明文。

## 本地 MongoDB

本地开发可用 Docker 启动 MongoDB，数据保存在 `local_data/mongo`：

```bash
mkdir -p local_data/secure
docker compose up -d mongo
scripts/mongo_ping.sh
```

`local_data/secure/mongo_root_password.txt` 需要与加密密钥库里的 `mongo.password` 一致。首次初始化 MongoDB 后不要随意修改该文件。

## NewsCrawler

新闻采集服务位于 `NewsCrawler/`，它独立写入 `news.raw_articles`、`news.crawl_runs`、`news.source_health` 等集合。DataHub 只读展示新闻库和采集健康状态；下游 ValueScope 分析只消费 DataHub 沉淀的数据，不直接请求新闻网站。

```bash
cd NewsCrawler
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/news-crawler sources
.venv/bin/news-crawler crawl --source tonghuashun --latest --max-pages 1 --dry-run
```

两个项目通过 `contracts/` 和 `NewsCrawler/contracts/` 中的 `news.v1` 文档契约通信。

## 测试与 CI

本地主要验证：

```bash
.venv/bin/python -m pytest -q tests
.venv/bin/python -m pytest -q NewsCrawler/tests
node --check stock_pipeline/web_static/admin-news.js
```

GitHub Actions 的 CI 已拆分为：

- `CI / hygiene`：敏感文件、Python 和 Shell 语法。
- `CI / tests`：ValueScope DataHub 与 NewsCrawler 测试。
- `CI / frontend-contract`：前端构建契约。
- `CI / compose`：生产 Compose 配置。
- `CI / docker-build`：生产镜像构建。
- `CI / validate`：聚合门禁，保留给分支保护使用。

## 部署

生产环境推荐 Docker Compose：

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

本机同步脚本：

```bash
alias tongbu="cd /Users/libingze/Desktop/sandbox/NewsAnalysis && scripts/tongbu.sh"
alias qiangzhitongbu="cd /Users/libingze/Desktop/sandbox/NewsAnalysis && scripts/qiangzhitongbu.sh"
```

`tongbu` 会同步代码并构建镜像；如果发现爬虫、冷备份上传或后台任务正在运行，会延迟激活新版本，不重启容器。`qiangzhitongbu` 会强制重启并立即激活新版本，适合确认可以中断任务时使用。

部署细节见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

## 数据与运维文档

- [docs/PROJECT_MASTER_PLAN_CN.md](docs/PROJECT_MASTER_PLAN_CN.md)：中文项目总规划、已完成能力、待建设路线图和技术路线。
- [docs/DATA_AND_OPERATIONS.md](docs/DATA_AND_OPERATIONS.md)：数据分层、冷备份、审计、自查、开盘啦和 NewsCrawler 运维说明。
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)：生产部署、安全同步、CI、GitHub Actions 和常用运维命令。
- [docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md)：项目简介。
- [docs/RELEASE_2_0.md](docs/RELEASE_2_0.md)：2.0 更名与发布说明。
- [docs/news_crawler_boundary.md](docs/news_crawler_boundary.md)：NewsCrawler / ValueScope DataHub 边界说明。

## 输出

默认输出到 `reports/{股票代码}_{时间戳}/`：

- `raw/*.json`：资料包构建过程中的原始结构化结果。
- `dossier.json`：压缩后的股票数据资料包，可供前端阅读和下游 ValueScope 分析使用。
- `analysis.md`：历史兼容的 DeepSeek / Agent 分析报告；新方向下主要保留为旧报告读取和数据供给验证入口。

持续对话保存在 `sessions/{股票代码}.json`。

## 免责声明

本项目输出只用于研究与辅助判断，不构成投资建议。股票价格受宏观、政策、流动性、公司治理和市场情绪等多因素影响，请结合自己的风险承受能力独立决策。
