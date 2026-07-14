# 后端分离规划

本规划用于后续重构 `stock_pipeline/web.py`，目标是让后端成为清晰的 API 与任务调度层，而不是把页面权限、数据 key、抓取方法、凭据规格和业务逻辑全部混在一个文件里。

## 当前已完成的后端边界

| 模块 | 职责 | 后续怎么用 |
| --- | --- | --- |
| `backend/paths.py` | 前端静态目录、OpenAPI 文件路径 | Web 服务只从这里拿静态资源路径 |
| `backend/auth_policy.py` | 管理员/只读管理员/普通数据台用户的页面权限 | 新页面先登记权限，再写路由 |
| `backend/fetch_registry.py` | 统一数据 key、抓取方法、资源等级、默认 provider | 新抓取入口先登记 fetch method，再接入 API/任务队列 |
| `backend/credentials_registry.py` | 凭据名称、来源、env、文件路径、安全展示字段 | 凭据页面和密钥写入逻辑只读这份规格 |

## 统一数据 key

| Key | 含义 | 热/冷 | 所属 |
| --- | --- | --- | --- |
| `stock.package` | 股票资料包 | hot | DataHub |
| `stock.daily_k` | 股票日K与覆盖索引 | hot | DataHub |
| `stock.minute` | 股票历史分时、冷备份索引、缓存 | cold | DataHub |
| `market.kaipanla` | 开盘啦行情 | hot | DataHub |
| `news.raw_article` | NewsCrawler 写入的新闻原文 | hot | NewsCrawler |
| `ops.audit` | 任务、审计、健康检查 | runtime | Backend |

## 统一抓取方法

| Method | 绑定数据 | 默认 provider | 资源级别 | 入口 |
| --- | --- | --- | --- | --- |
| `stock.package.sync` | `stock.package` | Eastmoney | heavy_io | `/api/sync-stock-data` |
| `stock.daily_k.sync` | `stock.daily_k` | Eastmoney | heavy_io | `/api/admin/daily-market-scheduler:run_now` |
| `stock.minute.backfill` | `stock.minute` | pytdx_history | heavy_io | `/api/sync-ths-market-data` |
| `stock.minute.market_fetch` | `stock.minute` | pytdx_history | heavy_io | `/api/admin/market-fetch/start` |
| `stock.storage.repair` | `stock.daily_k` | Eastmoney | heavy_io | `/api/admin/stock-storage-repair` |
| `market.kaipanla.run` | `market.kaipanla` | Kaipanla | normal_io | `/api/admin/kaipanla/scheduler:run_now` |
| `news.library.refetch` | `news.raw_article` | NewsCrawler | normal_io | `/api/admin/news-library/refetch` |
| `news.library.translate` | `news.raw_article` | Baidu Translate | normal_io | `/api/admin/news-library/translate` |
| `news.failure.retry` | `news.raw_article` | NewsCrawler | normal_io | `/api/admin/news-crawler/failure-action` |
| `analysis.single.run` | `stock.package` | DeepSeek | model_io | `/api/analyze` |
| `analysis.multi_agent.run` | `stock.package` | DeepSeek | model_io | `/api/multi-agent-analyze` |

## 下一步拆分顺序

1. `backend/accounts.py`：账户、归档账户、邀请码、只读管理员。
2. `backend/credentials.py`：凭据 snapshot、写入、删除、安全字段过滤。
3. `backend/tasks.py`：任务注册、队列入队、运行态恢复、资源压力保护。
4. `backend/routes_stock.py`：股票资料包、日K、存储状态、修复任务。
5. `backend/routes_market.py`：开盘啦、分时抓取、市场纵览。
6. `backend/routes_news.py`：NewsCrawler 只读状态、新闻库、失败项动作。
7. `backend/routes_ops.py`：系统治理、随机抽检、审计日志、后端注册表。

拆分原则：每一步都保留 `stock_pipeline/web.py` 作为入口，先把 handler/helper 移出去，再改测试，最后再考虑是否更换启动入口。
