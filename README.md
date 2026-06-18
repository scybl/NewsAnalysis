# Tushare Stock Analysis Pipeline

一个面向 A 股个股研究的流水线工程：输入股票代码，自动从 Tushare Pro 拉取行情、估值、财务、公司、行业、公告等数据，整理成结构化 dossier，然后调用 DeepSeek 生成可持续追问的分析对话。

## 快速开始

建议使用项目内虚拟环境，不使用全局 Python：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -r requirements.txt
```

`.env` 支持以下变量名：

```bash
TUSHARE_API=你的TushareToken
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
STOCK_WEB_USER=admin
STOCK_WEB_PASSWORD=请换成强密码
STOCK_WEB_SESSION_SECRET=一段随机字符串
STOCK_WEB_KEY_ENCRYPTION_SECRET=另一段长期固定的随机字符串
STOCK_WEB_INVITE_CODES=
STOCK_WEB_INVITE_TTL_SECONDS=259200
STOCK_WEB_DEMO_REQUEST_LIMIT=30
STOCK_WEB_DEMO_WINDOW_SECONDS=86400
STOCK_DATA_CACHE_TTL_SECONDS=86400
STOCK_ANALYSIS_HISTORY_REVIEW_LIMIT=3
STOCK_ANALYSIS_REUSE_TTL_SECONDS=1800
STOCK_ANALYSIS_REFRESH_TTL_SECONDS=3600
STOCK_AGENT_ENGINE=legacy
STOCK_AGENT_TEMPLATE=native
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DATABASE=news
MONGODB_COLLECTION=articles
```

也兼容 `TUSHARE_TOKEN`。DeepSeek key 不再放入 `.env`，请用管理员账号进入“账户管理”页，在“系统模型 Key”中验证并锁定。该 key 会使用 `STOCK_WEB_KEY_ENCRYPTION_SECRET` 加密保存；这个 secret 必须长期固定，变更后已保存的 key 将无法解密。

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

前端默认启用账号密码登录。若未配置，默认账号密码为 `admin/admin`，只适合本地测试；部署到服务器前请务必在 `.env` 中设置 `STOCK_WEB_USER`、`STOCK_WEB_PASSWORD` 和 `STOCK_WEB_SESSION_SECRET`。

注册功能只接受管理员后台生成的邀请码。管理员登录后可在“管理”面板生成 6 位数字邀请码，默认 3 天有效，成功注册后会被标记为已使用，不能再次注册。`STOCK_WEB_INVITE_CODES` 只作为可选启动种子，不建议日常使用。朋友测试账号也在管理员面板生成，默认每 24 小时最多 30 次 API 请求，可用 `STOCK_WEB_DEMO_REQUEST_LIMIT` 和 `STOCK_WEB_DEMO_WINDOW_SECONDS` 调整新生成测试账号的默认额度。

管理员后台分为账户管理和爬虫控制。账户管理可查看用户用量、配置系统 DeepSeek key、生成邀请码、生成 VIP 兑换码、发放/撤销用户 VIP、禁用/启用用户、重置测试账号额度，并查看后台任务和权限操作审计日志。禁用用户会立即移除该用户当前会话。

股票数据按股票代码共享保存到 `local_data/{ts_code}`，不是按用户隔离。`STOCK_DATA_CACHE_TTL_SECONDS` 控制共享缓存有效期，默认 24 小时内同一只股票不会重复调用 Tushare 更新。`STOCK_ANALYSIS_REUSE_TTL_SECONDS` 控制近期 DeepSeek / 多 Agent 分析结果的复用窗口，默认 30 分钟。`STOCK_ANALYSIS_HISTORY_REVIEW_LIMIT` 控制 LLM 分析时纳入最近几份历史分析做复盘，默认 3 份。

多 Agent 引擎默认使用稳定旧版 `legacy`。设置 `STOCK_AGENT_ENGINE=langgraph` 后会启用 LangGraph 工作流：第一轮专题 agent、反方审计、第二轮修正、最终汇总。该模式会增加一次审计和一次修正轮，结果更可审计，但会增加模型调用成本。

`STOCK_AGENT_TEMPLATE` 控制 LangGraph 里的角色模板：

- `native`：项目原生专题 agent。
- `tradingagents`：参考本地 `TradingAgents/` 仓库的投研交易图，包含市场、新闻、基本面、情绪、多头、空头、研究经理、交易员、激进/中性/保守风控和组合经理。
- `finrobot`：参考本地 `FinRobot/` 仓库的 equity report 链路，包含公司概览、投资更新、估值、风险、竞争分析、新闻摘要和核心结论。

LangGraph 模式会把每次最终结论写入 `local_data/{ts_code}/current/decision_memory.jsonl` 和 `local_data/agent_memory/global_decisions.jsonl`。下一次分析同一只股票或其他股票时，会读取最近几条决策记忆作为复盘上下文；这只保存分析结论摘要和运行 ID，不保存任何用户 API key。

账号分为管理员、VIP、普通用户和测试账号。管理员和 VIP 使用系统 `.env` 中的 Tushare / DeepSeek key；普通用户需要在页面内保存自己的 key。用户 key 会用 `STOCK_WEB_KEY_ENCRYPTION_SECRET` 派生的 Fernet 密钥加密保存，删除时会直接移除密文记录，不保留删除痕迹。管理员可在账户管理页生成 VIP 兑换码，并自定义兑换后的 VIP 天数；兑换码默认 3 天内有效，一次性使用。

抓取同花顺财经新闻到 MongoDB：

```bash
scripts/spider_crawl.sh
```

只抓新增新闻，适合日常定时运行：

```bash
SPIDER_TYPES=财经要闻,公司新闻 SPIDER_MAX_PAGES=3 scripts/spider_crawl.sh
```

本地 MongoDB 可用 Docker 启动，数据会保存在 `local_data/mongo`：

```bash
docker compose up -d mongo
scripts/mongo_ping.sh
```

抓取 dry-run 不写库：

```bash
scripts/spider_dry_run.sh
```

`stock_pipeline news crawl/search` 是旧 MySQL 新闻入口，当前建议使用 `spider/` 和上面的脚本抓取新闻。后续可再把 `stock_pipeline` 的新闻读取也统一迁到 MongoDB。

## 服务器部署

推荐使用 Docker Compose 部署，Web 和 MongoDB 会自动持续运行：

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

生产环境配置文件使用服务器上的 `.env`。可以从模板复制：

```bash
cp .env.deploy.sample .env
```

然后至少替换这些值：

```bash
TUSHARE_API=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
STOCK_WEB_PASSWORD=...
STOCK_WEB_SESSION_SECRET=...
STOCK_WEB_KEY_ENCRYPTION_SECRET=...
MONGO_PASSWORD=...
GUARDIAN_API_KEY=...
PUBLIC_WEB_PORT=8765
```

部署完成后，用管理员账号登录后台，在“账户管理 / 系统模型 Key”里录入 DeepSeek key。

从本机一键同步并部署到服务器。先创建只保存在本机的连接配置：

```bash
cp .deploy.env.sample .deploy.env
# 编辑 .deploy.env 后执行：
scripts/deploy_server.sh
```

本机部署脚本和 GitHub Actions 都不会上传 `.env`、用户数据、MongoDB 数据、会话、日志、报告、私钥、证书或本地数据库文件。生产 `.env` 只在服务器维护，`local_data` 等运行目录通过 Docker 卷持续保留。

本机脚本只会打包 Git 已跟踪的文件，已跟踪文件的本地修改可以直接发布；新建源码需要先执行 `git add 文件名`，避免项目目录里未纳入版本控制的私密文件被误传。

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

返回内容会包含 Web、Tushare/DeepSeek 配置状态、本地数据目录、爬虫状态和后台任务数量。生产环境可以用这个接口做 uptime 或反向代理探活。

`docker-compose.prod.yml` 使用 `restart: unless-stopped`，所以 Docker 启动后服务会自动恢复；Web 容器异常退出也会自动重启。服务器上建议只开放 Web 端口 `PUBLIC_WEB_PORT`，MongoDB 不对公网暴露。

如果希望全市场股票名称的拼音/首字母检索更完整，建议安装：

```bash
.venv/bin/python -m pip install -r requirements.txt
```

不安装也能使用代码、中文名检索，并内置支持一批常见股票名称拼音。

## 输出

默认输出到 `reports/{股票代码}_{时间戳}/`：

- `raw/*.json`：每个 Tushare 接口的原始结构化结果
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

不同 Tushare 接口有不同积分和权限要求；权限不足时会写入 `dossier["fetch_errors"]`。

## 免责声明

本项目输出只用于研究与辅助判断，不构成投资建议。股票价格受宏观、政策、流动性、公司治理和市场情绪等多因素影响，请结合自己的风险承受能力独立决策。
