# ValueScope / NewsAnalysis

一个面向 A 股研究和个人金融数据治理场景的多源数据中台。项目把股票资料包、日 K / 分钟行情、财经新闻采集、冷热分层存储、数据质量检查、后台任务调度、权限隔离和 LLM 投研分析组合成一个可部署、可运维、可演示的完整 Web 工程。

当前版本：`1.4.0`

## 项目定位

ValueScope / NewsAnalysis 更接近一个 **个人金融数据中台 + 后台运维控制台**：

- 采集层负责从东方财富、开盘啦、同花顺、通达信链路、Guardian 等来源接入市场、股票和新闻数据。
- 治理层负责数据源状态、覆盖范围、缺口追踪、随机抽检、审计报告和冷热分层归档。
- 存储层以 MongoDB 为热数据主库，本地缓存承接运行态文件，百度网盘承接低频访问的分时冷备份。
- 服务层向前端和分析模块提供统一 API，用于股票检索、行情阅读、新闻证据、后台任务和数据健康状态。
- 运维层提供账户、凭据、调度、爬虫状态、部署同步、任务审计和系统健康检查。

## 技术栈

| 层级 | 技术栈 | 用途 |
| --- | --- | --- |
| 后端服务 | Python 3、`http.server` / `ThreadingHTTPServer`、CLI | Web API、后台任务、数据同步和运维命令 |
| 数据存储 | MongoDB 7、PyMongo、JSON / JSONL、本地 `local_data`、百度网盘冷备份 | 热数据查询、运行态缓存、分时冷数据归档 |
| 行情数据 | 东方财富、开盘啦、同花顺、pytdx / mootdx / tdxpy、AkShare 候选源 | 股票资料包、日 K、分时、涨停连板、龙虎榜、市场情绪 |
| 新闻采集 | 独立 `NewsCrawler`、Requests、Selenium、BeautifulSoup、lxml | Guardian、同花顺、Bloomberg、Politico 等新闻源采集与标准化 |
| AI 分析 | DeepSeek、LangGraph 可选、多 Agent 投研链路 | 股票研究报告、反方审计、历史结论复盘 |
| 前端界面 | 原生 HTML / CSS / JavaScript | 数据中台首页、访问与安全、系统治理、股票数据、行情数据和新闻数据控制台 |
| 运维部署 | Docker Compose、GitHub Actions、Prometheus 可选、bdpan CLI | 生产部署、CI 校验、健康检查、百度网盘同步 |
| 安全治理 | Fernet 加密密钥库、TOTP、签名 Cookie、角色权限 | 管理员二次验证、凭据隔离、只读账号和后台操作审计 |
| 测试体系 | pytest、API smoke、集成测试、前端静态契约、回归测试、轻量性能基线 | 防止接口、页面、数据治理和部署脚本回归 |

> Tushare 目前处于封存状态：项目保留历史本地数据读取和必要回滚入口，但新的数据抓取与资料包更新不再默认依赖 Tushare。

这个仓库不是单一脚本，而是一个产品化系统：

- 前台提供股票检索、资料读取、分钟行情补采、多 Agent 分析和历史报告复用。
- 后台提供访问与安全、系统治理、只读展示账号、股票数据、行情数据、新闻数据、冷备份进度和任务审计。
- `NewsCrawler/` 作为独立新闻采集服务写入 MongoDB，`NewsAnalysis` 只读消费标准化 `news.v1` 文档。
- Docker Compose 部署 Web、MongoDB 和 NewsCrawler，支持一键同步到服务器。
- 敏感信息进入本地加密密钥库，不写入 `.env` 或仓库。

适合展示的只读账号：

```text
账号：admin_view
密码：admin_view
```

只读账号可以进入 Admin Console 查看系统治理、股票数据、行情数据、新闻数据、采集状态和任务记录，但不能触发抓取、保存、删除、生成分析或修改账号。

面试/展示材料：

- [项目简介](docs/PROJECT_BRIEF.md)
- [HR 演示指南](docs/HR_DEMO_GUIDE.md)
- [NewsCrawler / NewsAnalysis 边界说明](docs/news_crawler_boundary.md)
- [版本记录](CHANGELOG.md)

## 快速开始

建议使用项目内虚拟环境，不使用全局 Python：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -r requirements.txt
```

敏感信息不要写入 `.env`。首次运行先把管理员账号、会话密钥和连接密码写入本地加密密钥库：

```bash
.venv/bin/python -m stock_pipeline secrets set web.admin_username
.venv/bin/python -m stock_pipeline secrets set web.admin_password
.venv/bin/python -m stock_pipeline secrets set web.session_secret
.venv/bin/python -m stock_pipeline secrets set mongo.password
```

Tushare 当前封存，不作为新数据抓取的默认依赖；只有在你明确重新启用 Tushare 时，才需要配置 `tushare.api_token`。DeepSeek、Guardian、Bloomberg、Politico、百度网盘等运行凭据建议在管理员后台“访问与安全 / 凭据管理”中维护。

管理员账号支持 Authenticator/TOTP 二次验证。启用方式：

```bash
.venv/bin/python -m stock_pipeline secrets setup-admin-totp
```

命令会输出手动密钥和 `otpauth://` URI，只显示一次；把它添加到 Google Authenticator、Microsoft Authenticator、Authy 等应用后，管理员每次登录都需要账号、密码和 30 秒一次性验证码。不要把这段 URI 或手动密钥提交到 Git、截图或聊天记录。

如果已经有旧 `.env`，可以一次性迁移敏感项：

```bash
.venv/bin/python -m stock_pipeline secrets migrate-env
```

密钥库保存在 `local_data/secure/secrets.json.enc`，本地 master key 保存在 `local_data/secure/master.key`，两者都会设置为当前用户可读写。`.env` 只保留非敏感运行参数，例如 `DEEPSEEK_MODEL`、缓存 TTL、MongoDB host/collection 等。系统级 DeepSeek key 可用管理员账号进入“访问与安全 / 凭据管理”页验证并锁定；保存后不回显明文。

运行一次完整分析：

```bash
.venv/bin/python -m stock_pipeline analyze 000001.SZ
```

只采集数据，不调用 DeepSeek：

```bash
.venv/bin/python -m stock_pipeline collect 000001
```

默认会从 1990-01-01 开始尽量抓取全部历史数据；如果只想更新最近几年，可以加 `--years 8` 这类参数。

基于最近一次分析继续对话：

```bash
.venv/bin/python -m stock_pipeline chat 000001.SZ
```

启动简单前端：

```bash
scripts/run_web.sh
```

然后打开 `http://127.0.0.1:8765`，可以用股票代码、名称、首字母或拼音检索，例如 `000001`、`平安银行`、`mygf`、`muyuangufen`。

前端默认启用账号密码登录。若未配置，默认账号密码为 `admin/admin`，只适合本地测试；部署到服务器前请务必用 `stock_pipeline secrets set web.admin_username/web.admin_password/web.session_secret` 写入加密密钥库，并运行 `stock_pipeline secrets setup-admin-totp` 启用管理员 Authenticator 二次验证。

注册功能只接受管理员后台生成的邀请码。管理员登录后可在“访问与安全 / 用户与邀请码”生成 6 位数字邀请码，默认 3 天有效，成功注册后会被标记为已使用，不能再次注册。`STOCK_WEB_INVITE_CODES` 只作为可选启动种子，不建议日常使用。

管理员后台当前按实际运维域划分：访问与安全管理用户、邀请码、归档账号和外部服务凭据；系统治理集中展示运维状态、数据抽检和审计日志；股票数据管理资料包、日 K、分时覆盖和存储状态；行情数据管理开盘啦和全市场定时任务；新闻数据只读展示 NewsCrawler 的来源健康与采集运行。禁用用户会立即移除该用户当前会话。

股票数据按股票代码共享保存到 `local_data/{ts_code}`，不是按用户隔离。`STOCK_DATA_CACHE_TTL_SECONDS` 控制共享缓存有效期，默认 24 小时内同一只股票不会重复更新本地资料包。Tushare 封存期间，新抓取优先使用东方财富、腾讯兜底和本地缓存兼容数据。`STOCK_ANALYSIS_REUSE_TTL_SECONDS` 控制近期 DeepSeek / 多 Agent 分析结果的复用窗口，默认 30 分钟。`STOCK_ANALYSIS_HISTORY_REVIEW_LIMIT` 控制 LLM 分析时纳入最近几份历史分析做复盘，默认 3 份。

多 Agent 引擎默认使用稳定旧版 `legacy`。设置 `STOCK_AGENT_ENGINE=langgraph` 后会启用 LangGraph 工作流：第一轮专题 agent、反方审计、第二轮修正、最终汇总。该模式会增加一次审计和一次修正轮，结果更可审计，但会增加模型调用成本。

`STOCK_AGENT_TEMPLATE` 控制 LangGraph 里的角色模板：

- `native`：项目原生专题 agent。
- `tradingagents`：参考本地 `TradingAgents/` 仓库的投研交易图，包含市场、新闻、基本面、情绪、多头、空头、研究经理、交易员、激进/中性/保守风控和组合经理。
- `finrobot`：参考本地 `FinRobot/` 仓库的 equity report 链路，包含公司概览、投资更新、估值、风险、竞争分析、新闻摘要和核心结论。

LangGraph 模式会把每次最终结论写入 `local_data/{ts_code}/current/decision_memory.jsonl` 和 `local_data/agent_memory/global_decisions.jsonl`。下一次分析同一只股票或其他股票时，会读取最近几条决策记忆作为复盘上下文；这只保存分析结论摘要和运行 ID，不保存任何用户 API key。

管理员后台保留 **Agent Gateway** 调试页，但该入口当前暂停使用，不签发新的 `na_agent_...` token，`/api/agent/v1` 机器调用也会返回暂不可用。原设计权限为：

- `R`：读取本地股票、资料包和 Agent 任务。
- `B`：提交消耗系统 DeepSeek 额度的异步多 Agent 分析任务。

Agent API 位于 `/api/agent/v1`，OpenAPI 合约位于 `/api/agent/v1/openapi.json`。完整任务记录和 `Idempotency-Key` 重放结果保存在 `local_data/agent_jobs.json`；服务重启时未完成任务会标记为中断，不会假装继续运行。

仓库内 `mcp_server/` 是 Agent Gateway 的薄 MCP 包装，提供健康检查、股票搜索、本地资料读取和分析任务提交/轮询。MCP 只转发 scoped token，不接触管理员密码、浏览器 Cookie、数据源 key 或 DeepSeek key。安装与配置见 `mcp_server/README.md`。

访问与安全页面管理管理员、只读管理员、注册用户、邀请码、归档账号和系统凭据。普通用户的私有模型 key 继续由用户侧保存；系统级 DeepSeek、Guardian、Bloomberg、Politico、百度网盘等凭据通过凭据管理写入服务器安全目录，不在页面回显。旧 VIP / 临时账号接口仍兼容历史数据，但不再作为当前后台主流程展示。

股票基础列表由后台“每日股票数据”任务按北京时间自动刷新，默认时间为 `21:30`，不在普通用户前台提供手动刷新入口。其他会访问外部数据源或消耗 API/模型额度的手动动作默认需要审批确认，包括同步股票资料包、补抓分钟行情、单 Agent/多 Agent 分析和立即执行每日股票数据更新。后端会校验 `approved=true`，并把审批动作写入审计日志；如需关闭可设置非敏感参数 `DATA_FETCH_APPROVAL_REQUIRED=0`。

管理员后台的“系统治理”页是只读总览：`/admin-ops.html` 会读取 `/api/admin/ops/status`，展示后台任务、重 IO 占用、分时冷数据上传进度、数据覆盖、资源摘要和最近错误，并整合数据抽检和审计日志。该页面不会启动、停止或删除任务；重 IO 任务入口会在已有重 IO 运行时返回明确的 `blocking_tasks`，防止分时冷数据上传、全市场日 K 和空闲分钟预抓互相挤占服务器 IO。

新闻采集已经拆分为独立的 `NewsCrawler/` 项目。NewsAnalysis 不再请求新闻网站或启动新闻爬虫，只读取 NewsCrawler 写入的 `news.raw_articles`。

管理员后台的“新闻数据”页是只读运维视图：展示 `source_health`、`crawl_runs`、运行错误和数据所有权边界，不会从 NewsAnalysis 启动、停止或修改 NewsCrawler。

```bash
cd NewsCrawler
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/news-crawler sources
```

本地验证同花顺采集但不写库：

```bash
.venv/bin/news-crawler crawl --source tonghuashun --latest --max-pages 1 --dry-run
```

本地 MongoDB 可用 Docker 启动，数据会保存在 `local_data/mongo`：

```bash
mkdir -p local_data/secure
# 写入与加密密钥库 mongo.password 相同的 MongoDB 初始化密码，文件不会进入 Git。
# 首次启动 MongoDB 后不要随意改这个文件，否则已初始化实例仍使用旧密码。
docker compose up -d mongo
scripts/mongo_ping.sh
```

正式写入 MongoDB：

```bash
.venv/bin/news-crawler crawl --source all --latest --max-pages 1
```

Guardian 需要在 NewsCrawler 自己的环境中配置 `GUARDIAN_API_KEY`。Bloomberg 已作为正式 Provider 接入，默认优先使用 Bloomberg `lineup-next` API 获取 URL，并解析文章页 `__NEXT_DATA__` 正文；若服务器无法直连或触发登录墙/反爬，可通过部署 secret 设置 `BLOOMBERG_PROXY`、`BLOOMBERG_COOKIE`，或对应的 `BLOOMBERG_PROXY_FILE` / `BLOOMBERG_COOKIE_FILE`。Politico 使用公开 RSS feed 接入，可直接运行：

```bash
.venv/bin/news-crawler crawl --source politico --latest --max-articles 10 --dry-run
```

同时提供实验性的 `politico_browser` Provider，可用 Selenium/Chrome 直接尝试抓取 `https://www.politico.com/news/`。该源默认禁用；启用时需要 browser 依赖和可通过 Politico Cloudflare 验证的浏览器环境：

```bash
NEWS_CRAWLER_DISABLED_SOURCES= .venv/bin/news-crawler crawl --source politico_browser --latest --max-pages 1 --max-articles 5 --dry-run
```

`politico_browser` 支持 `POLITICO_BROWSER_PROFILE_DIR`、`POLITICO_BROWSER_PROXY` 和 `POLITICO_BROWSER_COOKIES_JSON`，用于复用已验证 profile、代理或注入 `cf_clearance` 等 Cookie。
服务器 Docker 启用该源时还需要设置 `NEWS_CRAWLER_INSTALL_BROWSER=1` 重新构建 crawler 镜像，并将 `POLITICO_BROWSER_PROFILE_DIR` 指向持久化目录，例如 `/app/local_data/politico_chrome_profile`。

NewsAnalysis 仍可独立检索已采集新闻：

```bash
.venv/bin/python -m stock_pipeline news search 牧原股份
```

两个项目只通过 `news.v1` 文档契约通信。契约文件分别位于 `contracts/` 和 `NewsCrawler/contracts/`。

### 股票数据

管理员后台“股票数据”页是统一的股票数据资产入口：上方展示本地缓存、同花顺、东方财富、AkShare 候选源和 Tushare 封存兼容状态，下方按标准数据类型归并为股票基础信息、日行情、分钟行情、涨停/连板、龙虎榜、板块、市场情绪、资金流、新闻、财务摘要和估值指标。

Tushare 现在默认处于 `archived` 封存状态：本地历史资料包仍可读取，但新同步、每日股票数据更新和搜索索引刷新不会默认调用 Tushare。股票资料包同步会优先使用东方财富 provider 生成兼容的 `full_data.datasets`，覆盖股票基础信息、日/周/月行情、估值快照、涨跌停估算、利润表、资产负债表、现金流量表、财务指标和行业归属。东方财富 K 线接口异常时会使用腾讯 K 线作为行情兜底，并在记录中标记 `source=tencent_fallback`。

### 开盘啦数据源

仓库已集成 `out_repo/kaipanla-crawler` 的全部公开功能，入口为：

```bash
python -m stock_pipeline kaipanla list
python -m stock_pipeline kaipanla validate
python -m stock_pipeline kaipanla run daily_data --params '{"end_date":"2026-01-16"}'
```

管理员后台不再为开盘啦设置独立导航模块；“行情数据”页统一提供开盘啦功能选择、参数 JSON、定时配置、立即抓取和本地记录查看。当前集成覆盖交易日完整数据、百日新高、连板梯队、板块排行/强度/资金、实时情绪、指数/个股/板块分时、板块新闻、龙虎榜、ETF、竞价 tick 等公开方法。个别功能可能依赖后续配置，例如 Selenium/Chrome 或开盘啦侧 Token/Cookie；这些功能会保留入口，便于后续补权限后继续调试。

## 服务器部署

推荐使用 Docker Compose 部署，NewsAnalysis Web、NewsCrawler 和 MongoDB 会分别持续运行：

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

NewsCrawler 单个来源的单次采集默认最多运行 300 秒，超时会把本次运行标记为 `failed`，错误码为 `timeout`，避免后台页面长期残留 `running`。如需调整，可设置 `NEWS_CRAWLER_MAX_RUNTIME_SECONDS=600`。

生产环境同样不要把 key 写入 `.env`。部署后在服务器目录执行：

```bash
.venv/bin/python -m stock_pipeline secrets set web.admin_password
.venv/bin/python -m stock_pipeline secrets set web.session_secret
.venv/bin/python -m stock_pipeline secrets set mongo.password
mkdir -p local_data/secure
# local_data/secure/mongo_root_password.txt 需与 mongo.password 相同，供 Docker 初始化 MongoDB 使用。
```

`.env` 只保留非敏感参数，例如：

```bash
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
PUBLIC_WEB_PORT=8765
```

部署完成后，用管理员账号登录后台，在“访问与安全 / 凭据管理”里录入 DeepSeek、新闻源和百度网盘等运行凭据。

从本机一键同步并部署到服务器。先创建只保存在本机的连接配置：

```bash
cp .deploy.env.sample .deploy.env
# 编辑 .deploy.env 后执行：
scripts/deploy_server.sh
```

常用本机快捷同步建议指向仓库脚本：

```bash
alias tongbu="cd /Users/libingze/Desktop/sandbox/NewsAnalysis && scripts/tongbu.sh"
alias qiangzhitongbu="cd /Users/libingze/Desktop/sandbox/NewsAnalysis && scripts/qiangzhitongbu.sh"
```

`tongbu` 是安全同步：先同步代码并构建镜像，部署前会检查 `local_data/admin_tasks.json` 里是否存在 `queued`、`running`、`stopping` 后台任务，也会检查分时冷备份、百度网盘上传进程，以及 `news-crawler` 运行记录中正在执行的新闻抓取。若有任务正在运行，会延迟激活新版本，只同步代码并构建镜像，不重启容器，因此不会打断抓取或上传；若没有运行任务，则会正常重启并激活新版本。

`qiangzhitongbu` 是强制同步并重启：跳过运行任务保护，同步代码、构建镜像，并通过 `docker compose up -d --build --force-recreate` 重建服务，用于你确认可以中断当前抓取、上传或预取任务，并需要立即激活新版本的时候。

分时冷备份上传应从独立 worker 启动，避免 web 容器部署时打断上传：

```bash
cd /opt/NewsAnalysis
scripts/start_minute_cold_worker_upload.sh
docker compose -f docker-compose.prod.yml exec -T minute-cold-worker tail -f /app/logs/minute-cold-stock-year-upload.log
```

本机部署脚本和 GitHub Actions 都不会上传 `.env`、用户数据、MongoDB 数据、会话、日志、报告、私钥、证书、本地数据库文件或 `local_data/secure` 密钥库。生产密钥库只在服务器维护，`local_data` 等运行目录通过 Docker 卷持续保留。

本机脚本只会打包 Git 已跟踪的文件，已跟踪文件的本地修改可以直接发布；新建源码需要先执行 `git add 文件名`，避免项目目录里未纳入版本控制的私密文件被误传。

如果服务器部署目录里已经混入历史遗留文件，先做 clean deploy dry-run：

```bash
DEPLOY_CLEAN=1 DEPLOY_CLEAN_DRY_RUN=1 scripts/deploy_server.sh
```

确认输出里只有应隔离的历史文件后，再执行真实清理部署：

```bash
DEPLOY_CLEAN=1 scripts/deploy_server.sh
```

clean deploy 会先保留 `.env`、`cache/`、`local_data/`、`logs/`、`reports/`、`sessions/`，把其他非白名单内容移动到 `DEPLOY_BACKUP_ROOT` 下带时间戳的备份目录，然后再同步当前 Git 跟踪文件并重建服务。这样可以把线上代码目录恢复到当前仓库形态，同时避免直接永久删除历史文件。

### 推送后自动部署

仓库内置了 `.github/workflows/deploy.yml`。向 `main` 推送成功后，GitHub Actions 会自动同步代码、重建服务并检查 `/api/health`；同一时间只会执行一个生产发布。

`.github/workflows/ci.yml` 会在 PR 和 `main` 更新时运行 `CI / validate`，检查敏感文件、Python/Shell 语法、前端 CSS、生产 Compose，并完整构建生产 Docker 镜像。`main` 分支保护要求这个检查通过后才能合并。

在 GitHub 仓库的 `Settings / Environments` 中创建 `production` 环境，并配置以下 Secrets：

- `DEPLOY_HOST`：服务器 IP 或域名（必填）
- `DEPLOY_USER`：SSH 用户，默认 `root`
- `DEPLOY_SSH_KEY`：能够登录服务器的 SSH 私钥（必填）
- `DEPLOY_KNOWN_HOSTS`：已核验的服务器 SSH 主机公钥记录（必填）
- `DEPLOY_PORT`：SSH 端口，默认 `22`
- `DEPLOY_PATH`：服务器目录，默认 `/opt/newsanalysis`
- `DEPLOY_HEALTH_URL`：服务器内部探活地址，默认 `http://127.0.0.1:8765/api/health`

对应公钥需要提前写入服务器用户的 `~/.ssh/authorized_keys`。生产 `.env` 仍只保存在服务器，不会从 GitHub Actions 上传。容器标签 `com.newsanalysis.release` 和 `com.newsanalysis.release-time` 会记录当前运行版本及发布时间。

`DEPLOY_KNOWN_HOSTS` 可以在可信网络中运行 `ssh-keyscan -p SSH端口 服务器地址` 获取；写入 Secret 前应通过云厂商控制台或服务器本地 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` 核对指纹，避免信任被冒充的服务器。

Ubuntu 服务器如果还没有 Docker，可以先在服务器上执行：

```bash
sudo bash scripts/server_install_docker_ubuntu.sh
```

常用运维命令：

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f web
docker compose -f docker-compose.prod.yml logs -f mongo
docker compose -f docker-compose.prod.yml restart web
docker compose -f docker-compose.prod.yml down
```

健康检查接口：

```bash
curl http://127.0.0.1:8765/api/health
```

返回内容会包含 Web 配置状态、本地数据目录、爬虫状态和后台任务数量。生产环境可以用这个接口做 uptime 或反向代理探活。

`docker-compose.prod.yml` 使用 `restart: unless-stopped`，所以 Docker 启动后服务会自动恢复；Web 容器异常退出也会自动重启。服务器上建议只开放 Web 端口 `PUBLIC_WEB_PORT`，MongoDB 不对公网暴露。

如果希望全市场股票名称的拼音/首字母检索更完整，建议安装：

```bash
.venv/bin/python -m pip install -r requirements.txt
```

不安装也能使用代码、中文名检索，并内置支持一批常见股票名称拼音。

## 输出

默认输出到 `reports/{股票代码}_{时间戳}/`：

- `raw/*.json`：资料包构建过程中的原始结构化结果；历史包可能保留旧 Tushare 文件名
- `dossier.json`：压缩后的股票研究资料包
- `analysis.md`：DeepSeek 首轮分析报告

持续对话保存在 `sessions/{股票代码}.json`，后续 `chat` 会自动加载上下文。

## 数据覆盖

流水线会尝试抓取：

- 基础信息：股票列表、上市公司信息、管理层、薪酬持股、曾用名
- 行情技术：日线、周线、月线、复权因子、每日指标、涨跌停、停复牌
- 财务年报/季报：利润表、资产负债表、现金流量表、财务指标、主营业务构成、分红、业绩预告/快报、审计意见、披露日期
- 股权参考：前十大股东、前十大流通股东、股东人数、增减持、质押、回购、限售解禁、大宗交易
- 资金交易：个股资金流向、融资融券明细
- 行业现状：申万行业归属、行业成分股、行业指数日行情
- 公告：上市公司公告，重点筛选年报/半年报/季报等标题

不同公开数据源可能存在限流、字段变动或权限缺口；失败会写入 `dossier["fetch_errors"]` 或对应任务日志。本地历史 Tushare 数据只作为兼容输入，新的默认抓取不依赖 Tushare。

## 免责声明

本项目输出只用于研究与辅助判断，不构成投资建议。股票价格受宏观、政策、流动性、公司治理和市场情绪等多因素影响，请结合自己的风险承受能力独立决策。
