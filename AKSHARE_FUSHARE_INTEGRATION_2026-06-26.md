# AkShare / fushare 接入评估与实现记录（2026-06-26）

## AkShare

- 官方文档入口：https://akshare.akfamily.xyz/introduction.html
- 安装方式：`pip install akshare --upgrade`
- 是否需要 API 申请：不需要。AkShare 是本地 Python 开源库，封装多个公开财经数据源。
- 接入方式：作为公开数据补源层，不替换东方财富主链路。

当前实现：

- 新增 `stock_pipeline.akshare_client.AkshareClient`
- 新增 `stock_pipeline.composite_client.FallbackStockClient`
- Web/CLI 默认公开源链路：
  - 主源：东方财富
  - 补源：AkShare
- 同类数据复用现有 key，避免重复数据集：
  - `daily` / `weekly` / `monthly`
  - `moneyflow`
  - `income`
  - `balancesheet`
  - `cashflow`
  - `fina_indicator`
  - `dividend`
  - `anns_d`
  - `stock_basic`
  - `stock_company`
  - `stk_holdernumber`
  - `share_float`
  - `top10_holders`

设计约束：

- 东方财富有数据时，保留东方财富结果，不再额外保存 `akshare_daily` 之类重复 key。
- 东方财富正常返回空、AkShare 源站失败时，保留主源空结果，不把空结果升级成错误。
- AkShare 公开源失败只作为补源失败处理，不阻塞主资料包。
- 全市场排行榜/统计类 AkShare 函数暂不塞入单只股票资料包，避免每只股票重复存大表。
- 财务三表来自 AkShare/东方财富公开接口时，关键字段映射到现有字段，并保留 `raw` 子字段，避免字段丢失。

真实样本验证：

- `000001.SZ`：
  - `fina_indicator`：可取 2024 年财务指标
  - `dividend`：可取 28 条历史分红
  - `anns_d`：可取巨潮公告

已知限制：

- AkShare 底层仍是公开网页/公开接口，行情和资金流等源可能被断开或限流。
- 当前接入优先覆盖单只股票资料包需要的数据；全市场类数据后续应放在市场级缓存，而不是单股资料包。

## fushare

- GitHub：https://github.com/LowinLi/fushare
- README 明确说明项目因个人原因不再维护，并建议关注 AkShare。
- 主要覆盖商品期货基本面：
  - 展期收益率
  - 注册仓单
  - 现货价格和基差
  - 会员持仓排名
  - 商品期货日线
- 与当前 A 股个股资料包目标不匹配。

结论：

- 暂不接入 fushare 到 A 股资料包主链路。
- 如果后续要做商品期货/CTA 模块，可以单独评估为期货数据源；不建议和股票资料包混存。
