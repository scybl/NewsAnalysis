# 部署与同步

本文记录 NewsAnalysis 的生产部署、同步策略和 CI 门禁。生产密钥和运行数据只保留在服务器，不进入 Git 仓库。

## 本地准备

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

敏感信息写入加密密钥库：

```bash
.venv/bin/python -m stock_pipeline secrets set web.admin_username
.venv/bin/python -m stock_pipeline secrets set web.admin_password
.venv/bin/python -m stock_pipeline secrets set web.session_secret
.venv/bin/python -m stock_pipeline secrets set mongo.password
.venv/bin/python -m stock_pipeline secrets setup-admin-totp
```

如果已有旧 `.env`，可以迁移敏感项：

```bash
.venv/bin/python -m stock_pipeline secrets migrate-env
```

`.env` 只保留非敏感运行参数，例如 `PUBLIC_WEB_PORT`、模型名、缓存 TTL、MongoDB host 等。

## 生产部署

推荐使用 Docker Compose：

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

服务器目录中需要维护生产密钥库，并保证 `local_data/secure/mongo_root_password.txt` 与 `mongo.password` 一致：

```bash
.venv/bin/python -m stock_pipeline secrets set web.admin_password
.venv/bin/python -m stock_pipeline secrets set web.session_secret
.venv/bin/python -m stock_pipeline secrets set mongo.password
mkdir -p local_data/secure
```

常用运维命令：

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f web
docker compose -f docker-compose.prod.yml logs -f mongo
docker compose -f docker-compose.prod.yml restart web
curl http://127.0.0.1:8765/api/health
```

`docker-compose.prod.yml` 使用 `restart: unless-stopped`，Docker 启动后服务会自动恢复。生产环境建议只开放 Web 端口，MongoDB 不对公网暴露。

## 本机同步脚本

建议在本机 `~/.zshrc` 中配置：

```bash
alias tongbu="cd /Users/libingze/Desktop/sandbox/NewsAnalysis && scripts/tongbu.sh"
alias qiangzhitongbu="cd /Users/libingze/Desktop/sandbox/NewsAnalysis && scripts/qiangzhitongbu.sh"
```

`tongbu` 是安全同步：同步代码并构建镜像；如果检测到后台任务、新闻爬虫、分时冷备份或百度网盘上传正在运行，会延迟激活新版本，不重启容器。

`qiangzhitongbu` 是强制同步：跳过运行任务保护，强制重建服务并立即激活新版本。只在确认可以中断抓取、上传或预取任务时使用。

部署脚本只打包 Git 已跟踪文件。新建源码、测试、脚本或文档需要先 `git add`，否则不会被同步到服务器。

## 分时冷备份 worker

分时冷备份上传应从独立 worker 启动，避免 Web 容器部署时打断上传：

```bash
cd /opt/NewsAnalysis
scripts/start_minute_cold_worker_upload.sh
docker compose -f docker-compose.prod.yml exec -T minute-cold-worker tail -f /app/logs/minute-cold-stock-year-upload.log
```

worker 容器挂载 bdpan 配置，只负责冷备份上传，不承载 Web 请求。

## Clean Deploy

如果服务器目录混入历史遗留文件，先做 dry-run：

```bash
DEPLOY_CLEAN=1 DEPLOY_CLEAN_DRY_RUN=1 scripts/deploy_server.sh
```

确认输出后再执行真实清理：

```bash
DEPLOY_CLEAN=1 scripts/deploy_server.sh
```

clean deploy 会保留 `.env`、`cache/`、`local_data/`、`logs/`、`reports/`、`sessions/`，把其他非白名单文件移动到备份目录，再同步当前 Git 跟踪文件。

## GitHub Actions

`.github/workflows/ci.yml` 在 PR 和 `main` 更新时运行拆分后的 CI：

- `CI / hygiene`：敏感文件、Python/Shell 语法。
- `CI / tests`：NewsAnalysis 与 NewsCrawler 测试。
- `CI / frontend-contract`：前端构建契约。
- `CI / compose`：生产 Compose 配置。
- `CI / docker-build`：生产镜像构建。
- `CI / validate`：聚合门禁，保留给分支保护使用。

`.github/workflows/deploy.yml` 在 `main` 推送后按环境 Secret 自动部署。生产 `.env` 和密钥库仍只保存在服务器，不会从 GitHub Actions 上传。

需要配置的 production Secrets：

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`
- `DEPLOY_KNOWN_HOSTS`
- `DEPLOY_PORT`
- `DEPLOY_PATH`
- `DEPLOY_HEALTH_URL`

`DEPLOY_KNOWN_HOSTS` 应通过云厂商控制台或服务器本地 SSH host key 指纹核对后再写入。
