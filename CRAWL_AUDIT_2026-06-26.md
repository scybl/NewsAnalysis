# 抓取相关测试与真实数据审计（2026-06-26）

## 执行范围

- 本地抓取/数据源/质量校验/NewsCrawler 相关测试：
  - `tests/test_eastmoney_client.py`
  - `tests/test_data_quality.py`
  - `tests/test_admin_crawler_frontend.py`
  - `tests/test_raw_news_contract.py`
  - `tests/test_admin_authentication.py`
  - `tests/test_web_security.py`
  - `NewsCrawler/tests/test_contract_copy.py`
  - `NewsCrawler/tests/test_dedupe.py`
  - `NewsCrawler/tests/test_health.py`
  - `NewsCrawler/tests/test_pipeline.py`
  - `NewsCrawler/tests/test_providers.py`
- 远程真实抓取验证：
  - `000001.SZ`
  - `000002.SZ`
  - `603132.SH`

## 结果

- 本地测试：`39 passed`
- 远程部署：成功，`/api/health` 正常
- 远程真实抓取：
  - `000001.SZ`：无 fetch error，日线/复权/财报/公告等可抓到长期历史；`moneyflow` 为空
  - `000002.SZ`：无 fetch error，日线/复权/财报/公告/质押明细等可抓到长期历史；`moneyflow` 为空
  - `603132.SH`：无 fetch error，日线从上市日 `20220222` 到 `20260626`，财报审计从上市年开始，不再误报上市前季度缺口

## 发现并处理的问题

1. `.venv` 缺少 pytest；安装最新版 pytest 后在本机 Python/readline 组合下发生段错误。
   - 处理：将本地 `.venv` 的 pytest 固定到 `7.4.0` 后测试可稳定运行。

2. 新上市公司财报质量审计误报。
   - 现象：`603132.SH` 上市前历史年报/季度披露不完整，被当成高严重度缺口。
   - 处理：质量审计读取 `stock_basic.list_date`，财报覆盖检查从上市年开始；新增回归测试。

3. 部分事件型数据为空时严重度过高。
   - 现象：停复牌、质押、名称变更等可能本来没有公开记录，不应直接等同抓取失败。
   - 处理：事件型空结果统一降为 low warning；连续历史型数据仍保留更高严重度。

4. `moneyflow` 历史源不稳定。
   - 现象：东方财富资金流接口对样本股多轮回退仍返回空。
   - 处理：已实现“能抓多少抓多少”的多区间回退与暂停重试；当前仍保留 medium warning，后续需要继续换更稳定的数据源。

## 当前仍需关注

- `moneyflow` 仍是主要缺口：不是代码异常，而是当前非 Tushare 历史资金流源返回空。
- `suspend_d` 按约定保持轻量 best-effort，不做三年逐日重扫；没有记录时仅提示 low warning。
- `stk_rewards` 已改为东方财富 F10 管理层结构化数据；可抓到高管薪酬/持股等字段，但不同公司披露字段完整度取决于源站。
