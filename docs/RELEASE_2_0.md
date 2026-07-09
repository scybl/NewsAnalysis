# ValueScope DataHub 2.0 发布说明

## 发布定位

2.0 版本将项目正式更名为 `ValueScope DataHub`。历史工程名 `NewsAnalysis` 继续作为代码包、服务器目录、冷备份路径和部分兼容接口保留，避免破坏已有部署和百度网盘冷数据索引。

新定位是：面向 A 股研究的数据采集、数据治理、冷热分层存储、质量检查和前端展示平台。下游 `ValueScope` 分析消费 DataHub 沉淀的数据，DataHub 本身不再作为主要分析引擎扩展。

## 相对于 1.x 的主要变化

| 模块 | 2.0 调整 |
| --- | --- |
| 产品命名 | 对外名称统一为 ValueScope DataHub，README、项目简介、公开作品集、MCP 文档和前端项目页已同步 |
| 项目边界 | 明确 NewsCrawler 负责新闻采集，DataHub 负责只读展示、治理和供给，下游 ValueScope 分析负责消费数据 |
| 数据治理 | 股票存储状态、分时冷备份索引、随机抽检、缺口记录和修复接口成为主线能力 |
| 运维后台 | 系统治理页集中承载运维状态、数据抽检和审计日志，任务状态和异常展示更适合长期运行 |
| 安全与访问 | 访问与安全页面统一管理注册用户、归档账号、邀请码、TOTP 和系统凭据 |
| 分析能力 | DeepSeek / 多 Agent 入口保留为历史报告读取和兼容供给记录，不作为 DataHub 新功能主线 |
| 发布材料 | 公开作品集改为展示数据平台设计、治理边界和脱敏预览，不公开生产源码、密钥或冷备份索引 |

## 兼容说明

- `/opt/NewsAnalysis` 服务器路径继续保留。
- `NewsAnalysis/cold/stock_minute/v1` 冷备份 remote root 继续保留。
- `newsanalysis-mcp` 包名继续保留，但描述改为 ValueScope DataHub gateway。
- 历史分析报告、Agent 任务和旧数据读取能力继续作为兼容入口存在。
- Tushare 仍处于封存状态，新的抓取、审计和补齐流程不应依赖 Tushare。

## 验收重点

- 首页、项目介绍、README 和公开作品集都应显示 ValueScope DataHub 定位。
- 运维、股票存储状态、冷备份索引和数据抽检功能应继续可用。
- NewsCrawler 与 DataHub 保持单向数据契约：`NewsCrawler -> raw_articles -> DataHub -> ValueScope 分析`。
- 部署脚本仍应从 Git 跟踪文件构建上传树，不依赖未跟踪文件。
