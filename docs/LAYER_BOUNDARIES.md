# ValueScope DataHub 分层边界

这个文件用于解决“所有东西写在一起”的问题。当前改造采用渐进迁移：先把可安全移动的前端静态资源移出 Python 包，再把后端和数据中台职责写成明确边界，后续逐个模块迁移，避免一次性改 imports 导致部署和长任务中断。

## 顶层目录

| 层 | 目录 | 负责什么 | 当前状态 |
| --- | --- | --- | --- |
| 前端 | `frontend/admin/` | 管理台 HTML、CSS、浏览器 JS、页面交互 | 已从 `stock_pipeline/web_static/` 拆出 |
| 后端 | `backend/` | Web API、鉴权、账户、凭据、任务调度、运行态控制、统一数据 key / 抓取方法注册表 | 已抽出注册表和策略模块，兼容路由入口仍在 `stock_pipeline/web.py` |
| 数据中台 | `datahub/` | 股票/行情/新闻读模型、覆盖索引、冷备份、质量检查、导出 | 先建立边界，兼容实现仍在 `stock_pipeline/*.py` |
| 兼容包 | `stock_pipeline/` | 旧 CLI、服务器入口、现有模块导入路径 | 保留，逐步拆分 |
| 新闻采集 | `NewsCrawler/` | 新闻 Provider、采集调度、新闻源健康 | 独立服务，DataHub 只读其 MongoDB 输出 |
| 运维脚本 | `scripts/` | 本地/服务器脚本、导出、审计、部署辅助 | 保留在顶层 |

## 文件放置规则

| 新需求 | 应放位置 | 不应放位置 |
| --- | --- | --- |
| 新管理台页面、按钮、表格、分页、状态文案 | `frontend/admin/` | `stock_pipeline/` Python 模块 |
| 新 API、权限、账户、凭据、安全逻辑 | `backend/` 注册表/策略模块；当前兼容路由入口仍可放 `stock_pipeline/web.py` | 前端 JS 直接读写数据 |
| 新后台任务、任务状态、资源节流 | 后端任务层；当前兼容放 `stock_pipeline/task_queue.py` 或调用它 | Web 请求线程直接跑重 IO |
| 新股票日K/分时/量价/覆盖逻辑 | 数据中台边界；当前兼容放相关 `stock_pipeline/*` 数据模块 | 前端页面临时计算核心数据 |
| 新冷备份上传、索引、按需取回 | 数据中台边界；当前兼容放 `minute_cold_storage.py` | 后端路由内直接拼远程对象 |
| 新新闻抓取 Provider | `NewsCrawler/` | DataHub 主站 |
| 新审计/导出脚本 | `scripts/` + 数据中台模块 | 临时一次性 notebook 或未跟踪文件 |

## 后续迁移顺序

1. 前端已迁移到 `frontend/admin/`，后续页面都从这里扩展。
2. 继续拆 `stock_pipeline/web.py`：已先抽出 `backend/paths.py`、`auth_policy.py`、`fetch_registry.py`、`credentials_registry.py`；下一步按账户/凭据、股票、行情、新闻、系统治理拆成 backend router/helper 模块，并保留 `web.py` 作为入口。
3. 拆数据模块：把股票热数据、分时冷数据、市场数据、新闻读模型、数据质量检查逐步迁到 DataHub 子模块，并保留旧 import shim。
4. 拆任务执行：长任务统一进入资源感知队列，必要时继续拆到独立 worker/container。
5. 每次迁移必须更新 `docs/ARCHITECTURE.md`、测试路径和部署说明。
