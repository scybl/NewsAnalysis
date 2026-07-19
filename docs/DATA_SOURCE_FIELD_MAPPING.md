# 数据源字段映射台账

最后更新：2026-07-19

本文档是 ValueScope DataHub 的字段映射台账，用来持续记录每个数据源返回的 key、DataHub 统一后的 key，以及最终写入 MongoDB 的位置和形态。字段名、dataset 名、collection 名、provider/API 名保留英文，便于和代码、数据库、测试直接对照。

## 维护规则

- 只要 provider、source API、标准 dataset key、数据库 collection、校验或 fallback 规则发生变化，就必须在同一个改动中更新本文档。
- 尽量把上游 raw key 和 DataHub 标准 key 放在同一行，方便核对。
- 如果某类数据故意保留原始嵌套结构，不逐字段标准化，必须明确标记为 `raw payload retained`。
- 修改 stock package 字段时，同步更新 `tests/test_akshare_client.py`、`tests/test_eastmoney_client.py`、`tests/test_data_sources.py` 或 storage 相关测试。
- 至少运行：
  - `python3 -m py_compile stock_pipeline/akshare_client.py stock_pipeline/eastmoney_client.py stock_pipeline/composite_client.py stock_pipeline/local_data_mongo.py`
  - 与本次修改相关的 provider/storage focused pytest。

## 存储模型

| 领域 | Mongo database.collection | 存储形态 | 字段统一发生的位置 |
| --- | --- | --- | --- |
| 股票包快照 | `stock_data.stock_packages` | 完整文档，包含 `full_data.datasets.<dataset>[]`、`dossier`、`analysis_dossiers` | provider client 在保存前返回标准 dataset rows |
| 股票包 metadata | `stock_data.stock_metadata` | `{ts_code, path, metadata, storage, synced_at}` | `stock_storage.sync_stock_data` 根据标准 package 生成 metadata |
| 股票 dataset rows | `stock_data.stock_dataset_rows` | `{ts_code, snapshot, dataset, row_key, trade_date, row, synced_at}` | `row` 是 provider 标准 row，Mongo 只增加 envelope 字段 |
| 日线覆盖率 | `stock_data.stock_daily_coverage` | 覆盖率审计文档 | 根据已存 daily rows 生成 |
| 分钟 bucket | `market_data.minute_day_buckets` | 每个 `{source, ts_code, trade_date}` 一条文档，包含 `minutes[]` | `ths_minute.py` 在 upsert bucket 前统一 minute rows |
| 开盘啦结果 | `market_data.kaipanla_results` | feature run envelope，核心数据在 `payload.result` | 保留 raw feature payload，只统一 envelope 字段 |
| 新闻原文 | `news.raw_articles` | `news.v1` raw article schema | NewsCrawler provider 在 repository 保存前统一 article 字段 |

`stock_dataset_rows.row_key` 从可识别行身份的字段生成，例如 `trade_date`、`ann_date`、`end_date`、`name`、`holder_name`，再加 row hash。`stock_dataset_rows.trade_date` 是便于搜索的 top-level 日期字段，取第一组可用的日期型 key；标准数据仍以 `row` 内字段为准。

## 股票包标准 Dataset

当前公共数据链路：

1. `AkshareClient` 是主数据源。
2. `EastmoneyClient` 负责验证和补齐 merge-safe dataset 中缺失字段；管理页的数据源 `status` 会直接决定 `_public_stock_client` 是否启用 AkShare/Eastmoney，禁用后不会被后台硬编码继续调用。
3. 腾讯行情在 `EastmoneyClient` 内部作为 daily/weekly/monthly K 线 fallback。
4. `TushareClient` 已归档，只在明确重新启用时使用。

`ValidatingStockClient` 中允许 merge/fill 的 dataset：`daily`、`weekly`、`monthly`、`daily_basic`、`adj_factor`、`stk_limit`、`moneyflow`、`margin_detail`、`income`、`balancesheet`、`cashflow`、`fina_indicator`、`dividend`、`anns_d`、`stock_basic`、`stock_company`、`stk_holdernumber`、`share_float`、`top10_holders`。合并只填同一 identity row 的缺失值，不覆盖主源已有值。

`safe empty` dataset：`suspend_d`、`disclosure_date`、`pledge_stat`、`pledge_detail`、`repurchase`、`sw_daily`。当 AkShare 未映射或失败、Eastmoney 明确返回空 rows 时，DataHub 保留同名空 dataset，不把它记作抓取异常；这表示“该股票/区间可合法无事件”，不是表示上游有非空数据。

| Dataset | `full_data.datasets` / `stock_dataset_rows.row` 标准 key | Merge identity | 必需质量字段 |
| --- | --- | --- | --- |
| `stock_basic` | `ts_code`, `symbol`, `name`, `fullname`, `area`, `industry`, `market`, `list_date`, `exchange`, `list_status`, `source` | `ts_code` | `ts_code`, `name`, `list_date` |
| `namechange` | `ts_code`, `name`, `start_date`, `end_date`, `change_reason`, `source` | 不 merge | 无 |
| `stock_company` | `ts_code`, `com_name`, `exchange`, `chairman`, `manager`, `secretary`, `reg_capital`, `setup_date`, `province`, `city`, `introduction`, `website`, `email`, `office`, `employees`, `main_business`, `business_scope`, `source`, optional `raw` | `ts_code` | `ts_code`, `com_name` |
| `stk_managers` | `ts_code`, `name`, `title`, `gender`, `lev`, `reward`, `hold_vol`, `edu`, `age`, `begin_date`, `source` | 不 merge | 无 |
| `stk_rewards` | 与高管薪酬 row 形态一致 | 不 merge | 无 |
| `daily`, `weekly`, `monthly` | `ts_code`, `trade_date`, `open`, `close`, `high`, `low`, `vol`, `amount`, `pct_chg`, `change`, optional `turnover_rate`, `source` | `trade_date`；validator 只补缺失字段，不覆盖主源已有 OHLC/volume | `trade_date`, `open`, `high`, `low`, `close`, `vol`, `amount` |
| `daily_basic` | `ts_code`, `trade_date`, `close`, `turnover_rate`, optional `volume_ratio`, `pe`, `pe_ttm`, `pb`, `total_mv`, `circ_mv`, `source` | `trade_date` | `trade_date`, `close`, `turnover_rate` |
| `adj_factor` | `ts_code`, `trade_date`, `adj_factor`, `source` | `trade_date` | 无 |
| `stk_limit` | `ts_code`, `trade_date`, `up_limit`, `down_limit`, `source` | `trade_date` | 无 |
| `suspend_d` | `ts_code`, `suspend_date`, `resume_date`, `suspend_timing`, `resume_timing`, `suspend_type`, `reason`, `source` | 不 merge | 无 |
| `moneyflow` | `ts_code`, `trade_date`, `close`, `pct_chg`, `net_mf_amount`, `net_mf_vol`, `buy_elg_amount`, `buy_lg_amount`, `buy_md_amount`, `buy_sm_amount`, optional volume detail, `net_mf_ratio`, `source` | `trade_date` | `trade_date`, `net_mf_amount`, `buy_elg_amount`, `buy_lg_amount`, `buy_md_amount`, `buy_sm_amount` |
| `margin_detail` | `ts_code`, `trade_date`, `rzye`, `rqye`, `rzmre`, `rzche`, `rzjme`, `rqyl`, `rqmcl`, `rqchl`, `rzrqye`, `source` | `trade_date` | 无 |
| `income` | `ts_code`, `ann_date`, `f_ann_date`, `end_date`, `report_type`, `total_revenue`, `revenue`, `oper_cost`, `operate_profit`, `total_profit`, `n_income`, `n_income_attr_p`, `income_tax`, `basic_eps`, `diluted_eps`, `source`, optional `raw` | `end_date` | `end_date`, `total_revenue`, `n_income` |
| `balancesheet` | `ts_code`, `ann_date`, `f_ann_date`, `end_date`, `report_type`, `total_assets`, `total_liab`, `total_hldr_eqy_exc_min_int`, `total_hldr_eqy_inc_min_int`, `money_cap`, `accounts_receiv`, `inventories`, `total_cur_assets`, `total_cur_liab`, `fix_assets`, `source`, optional `raw` | `end_date` | `end_date`, `total_assets`, `total_liab` |
| `cashflow` | `ts_code`, `ann_date`, `f_ann_date`, `end_date`, `report_type`, `net_profit`, `n_cashflow_act`, `n_cashflow_inv_act`, `n_cash_flows_fnc_act`, `c_cash_equ_end_period`, `source`, optional `raw` | `end_date` | `end_date`, `n_cashflow_act` |
| `fina_indicator` | `ts_code`, `ann_date`, `end_date`, `eps`, `dt_eps`, `roe`, `roe_waa`, `roe_dt`, `roa`, `grossprofit_margin`, `netprofit_margin`, `assets_turn`, `current_ratio`, `quick_ratio`, `debt_to_assets`, `total_assets`, `netprofit_yoy`, `assets_yoy`, `or_yoy`, `ocfps`, `source` | `end_date` | `end_date`, `roe`, `debt_to_assets` |
| `express` | `ts_code`, `ann_date`, `end_date`, `revenue`, `n_income`, `diluted_eps`, `bps`, `yoy_net_profit`, `yoy_sales`, `source` | 不 merge | 无 |
| `forecast` | `ts_code`, `ann_date`, `end_date`, `type`, `p_change_min`, `p_change_max`, `net_profit_min`, `net_profit_max`, `summary`, `change_reason`, `source` | 不 merge | 无 |
| `dividend` | `ts_code`, `ann_date`, `end_date`, `record_date`, `ex_date`, `pay_date`, `stk_div`, `stk_bo_rate`, `cash_div`, `div_proc`, `div_plan`, `implementation`, `source` | `ann_date`, `end_date` | `ann_date`, `cash_div` |
| `fina_mainbz` | `ts_code`, `end_date`, `bz_item`, `bz_code`, `bz_sales`, `bz_profit`, `bz_cost`, `curr_type`, `source` | 不 merge | 无 |
| `fina_audit` | `ts_code`, `end_date`, `audit_result`, `audit_fees`, `audit_agency`, `source` | 不 merge | 无 |
| `top10_holders`, `top10_floatholders` | `ts_code`, `ann_date`, `end_date`, `holder_name`, `hold_amount`, `hold_ratio`, `holder_type`, `rank`, `holder_num`, `avg_hold`, `source` | `end_date`, `holder_name` | `end_date`, `holder_name`, `hold_amount`, `hold_ratio` |
| `stk_holdernumber` | `ts_code`, `ann_date`, `end_date`, `holder_num`, `holder_num_prev`, `holder_num_change`, `change`, `change_ratio`, `avg_hold`, `avg_hold_amt`, `avg_mv`, `total_share`, `total_mv`, `source` | `end_date` | `end_date`, `holder_num` |
| `stk_holdertrade` | `ts_code`, `ann_date`, `holder_name`, `change_vol`, `change_ratio`, `after_share`, `after_ratio`, `source` | 不 merge | 无 |
| `pledge_stat` | `ts_code`, `end_date`, `pledge_count`, `unrest_pledge`, `rest_pledge`, `total_share`, `pledge_ratio`, `source` | 不 merge | 无 |
| `pledge_detail` | `ts_code`, `ann_date`, `holder_name`, `pledge_amount`, `pledge_ratio`, `total_share_ratio`, `pledgee`, `pledgee_type`, `start_date`, `end_date`, `is_release`, `release_date`, `status`, `warning_state`, `warning_line`, `open_line`, `purpose`, `source` | 不 merge | 无 |
| `share_float` | `ts_code`, `ann_date`, `float_date`, `float_share`, `total_share`, `limit_share`, `float_ratio`, `holder_name`, `share_type`, `change_reason`, `source` | `float_date` | `float_date`, `float_share` |
| `block_trade` | `ts_code`, `trade_date`, `price`, `vol`, `amount`, `buyer`, `seller`, `source` | 不 merge | 无 |
| `index_member_all` | `ts_code`, `l1_code`, `l1_name`, `l2_code`, `l2_name`, `l3_code`, `l3_name`, `is_new`, `source` | 不 merge | 无 |
| `anns_d` | `ts_code`, `ann_date`, `title`, `url`, optional `type`, `source` | `ann_date`, `title` | `ann_date`, `title`, `url` |

## AkShare 字段映射

AkShare 是主数据源。财报类 row 保留 `raw`，避免未映射的上游字段丢失。

| AkShare API | 使用的上游返回 key | DataHub dataset.key |
| --- | --- | --- |
| `stock_zh_a_hist` | `日期` -> `trade_date`; `开盘` -> `open`; `收盘` -> `close`; `最高` -> `high`; `最低` -> `low`; `成交量` -> `vol`; `成交额` -> `amount`; `涨跌幅` -> `pct_chg`; `涨跌额` -> `change`; `换手率` -> `turnover_rate` | `daily` / `weekly` / `monthly` |
| `stock_zh_a_daily` fallback | `date` -> `trade_date`; `open` / `high` / `low` / `close`; `volume` 以股返回，转换为 `vol` 手; `amount` -> `amount`; `turnover` 以比例返回，乘以 100 后写入 `turnover_rate`; `weekly` / `monthly` 由 daily 聚合 OHLC、`vol`、`amount`、`turnover_rate` | `daily` / 聚合 `weekly` / 聚合 `monthly` |
| Derived from `stock_zh_a_hist` | 标准 K 线中的 `trade_date`, `close`, `turnover_rate` | `daily_basic.trade_date`, `daily_basic.close`, `daily_basic.turnover_rate` |
| `stock_individual_fund_flow` | `日期` -> `trade_date`; `收盘价` -> `close`; `涨跌幅` -> `pct_chg`; `主力净流入-净额` -> `net_mf_amount`; `主力净流入-净占比` -> `net_mf_ratio`; `超大单净流入-净额` -> `buy_elg_amount`; `大单净流入-净额` -> `buy_lg_amount`; `中单净流入-净额` -> `buy_md_amount`; `小单净流入-净额` -> `buy_sm_amount` | `moneyflow` |
| `stock_profit_sheet_by_report_em` | `报告日` / `REPORT_DATE` / `日期` -> `end_date`; `公告日期` / `NOTICE_DATE` -> `ann_date`; `营业总收入` / `TOTAL_OPERATE_INCOME` / `OPERATE_INCOME` -> `total_revenue`; `营业收入` / `OPERATE_INCOME` / `TOTAL_OPERATE_INCOME` -> `revenue`; `营业成本` / `OPERATE_COST` / `TOTAL_OPERATE_COST` -> `oper_cost`; `营业利润` / `OPERATE_PROFIT` -> `operate_profit`; `利润总额` / `TOTAL_PROFIT` -> `total_profit`; `净利润` / `NETPROFIT` / `PARENT_NETPROFIT` -> `n_income`; `归属于母公司股东的净利润` / `PARENT_NETPROFIT` -> `n_income_attr_p`; `基本每股收益` / `BASIC_EPS` -> `basic_eps`; `稀释每股收益` / `DILUTED_EPS` -> `diluted_eps` | `income`，保留完整 `raw` |
| `stock_balance_sheet_by_report_em` | `报告日` / `REPORT_DATE` / `日期` -> `end_date`; `公告日期` / `NOTICE_DATE` -> `ann_date`; `资产总计` / `TOTAL_ASSETS` -> `total_assets`; `负债合计` / `TOTAL_LIABILITIES` -> `total_liab`; `归属于母公司股东权益合计` / `TOTAL_PARENT_EQUITY` / `TOTAL_EQUITY` -> `total_hldr_eqy_exc_min_int`; `所有者权益合计` / `TOTAL_EQUITY` -> `total_hldr_eqy_inc_min_int`; `货币资金` / `MONETARYFUNDS` / `MONETARY_FUND` -> `money_cap`; `应收账款` / `ACCOUNTS_RECE` / `ACCOUNTS_RECEIVABLE` -> `accounts_receiv`; `存货` / `INVENTORY` / `INVENTORIES` -> `inventories`; `固定资产` / `FIXED_ASSET` / `FIX_ASSET` -> `fix_assets` | `balancesheet`，保留完整 `raw` |
| `stock_cash_flow_sheet_by_report_em` | `报告日` / `REPORT_DATE` / `日期` -> `end_date`; `公告日期` / `NOTICE_DATE` -> `ann_date`; `净利润` / `NETPROFIT` -> `net_profit`; `经营活动产生的现金流量净额` / `NETCASH_OPERATE` -> `n_cashflow_act`; `投资活动产生的现金流量净额` / `NETCASH_INVEST` -> `n_cashflow_inv_act`; `筹资活动产生的现金流量净额` / `NETCASH_FINANCE` -> `n_cash_flows_fnc_act`; `期末现金及现金等价物余额` / `END_CCE` -> `c_cash_equ_end_period` | `cashflow`，保留完整 `raw` |
| `stock_financial_analysis_indicator` | `日期` -> `end_date`; `摊薄每股收益(元)` / `加权每股收益(元)` -> `eps`; `扣除非经常性损益后的每股收益(元)` -> `dt_eps`; `净资产收益率(%)` -> `roe`; `加权净资产收益率(%)` -> `roe_waa`; `销售毛利率(%)` -> `grossprofit_margin`; `销售净利率(%)` -> `netprofit_margin`; `总资产周转率(次)` -> `assets_turn`; `流动比率` -> `current_ratio`; `速动比率` -> `quick_ratio`; `资产负债率(%)` -> `debt_to_assets`; `总资产(元)` -> `total_assets`; `净利润增长率(%)` -> `netprofit_yoy`; `总资产增长率(%)` -> `assets_yoy` | `fina_indicator` |
| `stock_dividend_cninfo` | `实施方案公告日期` -> `ann_date`; `股权登记日` -> `record_date`; `除权日` -> `ex_date`; `派息日` -> `pay_date`; `送股比例` -> `stk_div`; `转增比例` -> `stk_bo_rate`; `派息比例` -> `cash_div`; `分红类型` -> `div_proc`; `实施方案分红说明` -> `div_plan`; `报告时间` -> `end_date` | `dividend` |
| `stock_zh_a_disclosure_report_cninfo` | `公告时间` -> `ann_date`; `公告标题` -> `title`; `公告链接` -> `url` | `anns_d` |
| `stock_individual_info_em` | `item` / `项目` / `指标` 与 `value` / `值`; 选取 `股票简称` / `名称` -> `name` and `com_name`; `行业` -> `industry`; `市场` -> `market`; `上市时间` / `上市日期` -> `list_date`; `主营业务` -> `main_business`; `总股本` -> `reg_capital`; company row 保留完整 `raw` | `stock_basic`, `stock_company` |
| `stock_zh_a_gdhs_detail_em` | `股东户数统计截止日` -> `end_date`; `股东户数公告日期` -> `ann_date`; `股东户数-本次` -> `holder_num`; `股东户数-上次` -> `holder_num_prev`; `股东户数-增减` -> `change`; `股东户数-增减比例` -> `change_ratio`; `户均持股数量` -> `avg_hold`; `户均持股市值` -> `avg_mv`; `总股本` -> `total_share`; `总市值` -> `total_mv` | `stk_holdernumber` |
| `stock_zh_a_gbjg_em` | `变更日期` -> `float_date` and `ann_date`; `已流通股份` / `已上市流通A股` -> `float_share`; `总股本` -> `total_share`; `流通受限股份` -> `limit_share`; `变动原因` -> `change_reason` | `share_float` |
| `stock_main_stock_holder` | `截至日期` -> `end_date`; `公告日期` -> `ann_date`; `股东名称` / `股东` -> `holder_name`; `持股数量` -> `hold_amount`; `持股比例` -> `hold_ratio`; `股东总数` -> `holder_num`; `平均持股数` -> `avg_hold` | `top10_holders` |

## Eastmoney 校验与 Fallback 映射

Eastmoney 作为同一批 dataset key 的 validator/fallback，同时也提供部分 AkShare 当前未覆盖的数据。

| Eastmoney endpoint/report | 使用的上游返回 key | DataHub dataset.key |
| --- | --- | --- |
| `push2his stock/kline/get` `klines` with `fields2=f51..f61` | comma parts: `0 date`, `1 open`, `2 close`, `3 high`, `4 low`, `5 vol`, `6 amount`, `8 pct_chg`, `9 change`, `10 turnover_rate` | `daily` / `weekly` / `monthly`; `daily_basic` 使用 `close` 和 `turnover_rate` |
| Tencent fallback inside Eastmoney | Tencent row array: `date`, `open`, `close`, `high`, `low`, `vol`; 计算 `change`, `pct_chg`; `amount` 通常为 `None` | `daily` / `weekly` / `monthly` fallback rows，`source=tencent_*_fallback` |
| `push2 stock/get` snapshot fields | `f116` -> `total_mv`; `f117` -> `circ_mv`; `f162` -> `pe` and `pe_ttm`; `f167` -> `pb`; `f10` -> `volume_ratio` | 补充 `daily_basic` |
| raw and adjusted K line ratio | raw close vs adjusted close | `adj_factor.adj_factor` |
| Derived from K line | previous close plus ratio | `stk_limit.up_limit`, `stk_limit.down_limit` |
| `RPT_CUSTOM_SUSPEND_DATA_INTERFACE` | `SUSPEND_START_DATE` / `SUSPEND_START_TIME` -> `suspend_date`; `PREDICT_RESUME_DATE` / `SUSPEND_END_TIME` -> `resume_date`; `SUSPEND_EXPIRE` -> `suspend_type`; `SUSPEND_REASON` -> `reason` | `suspend_d` |
| F10 organization / finance rows | `SECURITY_NAME_ABBR`, `ORG_NAME`, `REGIONBK`, `PROVINCE`, `EM2016`, `INDUSTRY_NAME`, `TRADE_MARKET`, `MARKET`, `LISTING_DATE`, `FORMERNAME` | `stock_basic`, `namechange` |
| F10 organization detail | `ORG_NAME`, `CHAIRMAN`, `PRESIDENT`, `SECRETARY`, `REG_CAPITAL`, `FOUND_DATE`, `PROVINCE`, `ADDRESS`, `ORG_PROFILE`, `ORG_PROFIE`, `ORG_WEB`, `ORG_EMAIL`, `EMP_NUM`, `MAIN_BUSINESS`, `BUSINESS_SCOPE`, `ACCOUNT_FIRM` | `stock_company`, `fina_audit` |
| `PC_HSF10/CompanyManagement/PageAjax` | `gglb` rows: `PERSON_NAME`, `POSITION`, `SALARY`, `HOLD_NUM`, `SEX`, `HIGH_DEGREE`, `AGE`, `INCUMBENT_TIME` | `stk_managers`, `stk_rewards` |
| `RPT_DMSK_FN_INCOME` | `NOTICE_DATE`, `REPORT_DATE`, `REPORT_TYPE_CODE`, `TOTAL_OPERATE_INCOME`, `OPERATE_PROFIT`, `TOTAL_PROFIT`, `PARENT_NETPROFIT`, `INCOME_TAX` | `income` |
| `RPT_DMSK_FN_BALANCE` | `NOTICE_DATE`, `REPORT_DATE`, `REPORT_TYPE_CODE`, `TOTAL_ASSETS`, `TOTAL_LIABILITIES`, `TOTAL_EQUITY`, `MONETARYFUNDS`, `ACCOUNTS_RECE`, `INVENTORY`, `TOTAL_CURRENT_ASSETS`, `TOTAL_CURRENT_LIAB`, `FIXED_ASSET` | `balancesheet` |
| `RPT_DMSK_FN_CASHFLOW` | `NOTICE_DATE`, `REPORT_DATE`, `REPORT_TYPE_CODE`, `NETPROFIT`, `NETCASH_OPERATE`, `NETCASH_INVEST`, `NETCASH_FINANCE`, `END_CCE` | `cashflow` |
| `RPT_F10_FINANCE_MAINFINADATA` | `NOTICE_DATE`, `REPORT_DATE`, `EPSJB`, `EPSXS`, `ROEJQ`, `ROEKCJQ`, `ZZCJLL`, `XSMLL`, `XSJLL`, `ZCFZL`, `LD`, `SD`, `TOTALOPERATEREVETZ`, `PARENTNETPROFITTZ`, `MGJYXJJE` | `fina_indicator` |
| `push2his stock/fflow/daykline/get` `klines` | comma parts: `0 date`, `1 net_mf_amount`, `2 buy_sm_amount`, `3 buy_md_amount`, `4 buy_lg_amount`, `5 buy_elg_amount`, `6 net_mf_vol`, `7 buy_sm_vol`, `8 buy_md_vol`, `9 buy_lg_vol`, `10 buy_elg_vol`, `11 close`, `12 pct_chg` | `moneyflow` |
| `RPTA_WEB_RZRQ_GGMX` | `DATE`, `RZYE`, `RQYE`, `RZMRE`, `RZCHE`, `RZJME`, `RQYL`, `RQMCL`, `RQCHL`, `RZRQYE` | `margin_detail` |
| `RPT_F10_EH_HOLDERS` / `RPT_F10_EH_FREEHOLDERS` | `UPDATE_DATE`, `END_DATE`, `HOLDER_NAME`, `HOLD_NUM`, `HOLD_NUM_RATIO` / `FREE_HOLDNUM_RATIO`, `HOLDER_TYPE`, `HOLDER_RANK` | `top10_holders`, `top10_floatholders` |
| `RPT_F10_EH_HOLDERNUM` | `NOTICE_DATE`, `END_DATE`, `HOLDER_TOTAL_NUM`, `HOLDER_TOTAL_NUMCHANGE`, `AVG_HOLD_AMT` | `stk_holdernumber` |
| Derived from holders | holder snapshot fields | `stk_holdertrade` |
| `RPTA_APP_ACCUMDETAILS` | `NOTICE_DATE`, `HOLDER_NAME`, `PF_NUM`, `PF_HOLD_RATIO`, `PF_TSR`, `PF_ORG`, `PFORG_TYPE`, `PF_START_DATE`, `UNFREEZE_DATE`, `UNFREEZE_STATE`, `ACTUAL_UNFREEZE_DATE`, `WARNING_STATE`, `WARNING_LINE`, `OPENLINE`, `PF_PURPOSE` / `PF_REASON` | `pledge_detail`; 按日期聚合为 `pledge_stat` |
| `RPT_SHAREBONUS_DET` | `NOTICE_DATE` / `PLAN_NOTICE_DATE`, `REPORT_DATE`, `ASSIGN_PROGRESS`, `BONUS_IT_RATIO`, `PRETAX_BONUS_RMB`, `EQUITY_RECORD_DATE`, `EX_DIVIDEND_DATE`, `IMPL_PLAN_PROFILE` | `dividend` |
| `RPT_PUBLIC_OP_NEWPREDICT` | `NOTICE_DATE`, `REPORT_DATE`, `PREDICT_TYPE`, `PREDICT_RATIO_LOWER` / `ADD_AMP_LOWER`, `PREDICT_RATIO_UPPER` / `ADD_AMP_UPPER`, `PREDICT_AMT_LOWER`, `PREDICT_AMT_UPPER`, `PREDICT_CONTENT`, `CHANGE_REASON_EXPLAIN` | `forecast` |
| `RPT_LICO_FN_CPD` | `NOTICE_DATE`, `REPORTDATE`, `TOTAL_OPERATE_INCOME`, `PARENT_NETPROFIT`, `BASIC_EPS`, `BPS`, `SJLTZ`, `YSTZ` | `express` |
| `RPT_F10_FN_MAINOP` | `REPORT_DATE`, `ITEM_NAME`, `ITEM_CODE`, `MAIN_BUSINESS_INCOME`, `MAIN_BUSINESS_RPOFIT`, `MAIN_BUSINESS_COST` | `fina_mainbz` |
| `RPT_LIFT_STAGE` | `FREE_DATE`, `FREE_SHARES`, `FREE_RATIO`, `FREE_SHARES_TYPE` | `share_float` |
| `RPT_DATA_BLOCKTRADE` | `TRADE_DATE`, `DEAL_PRICE`, `DEAL_VOLUME`, `DEAL_AMT`, `BUYER_NAME`, `SELLER_NAME` | `block_trade` |
| `np-anotice-stock` | `notice_date` / `NOTICE_DATE` / `display_time`, `title` / `TITLE`, `attach_url` / `ATTACH_URL` / `url`, `columns[].column_name` | `anns_d` |

## Tushare 历史兼容映射

`TushareClient` 提交 `{api_name, params, fields}`，并把返回的 `data.fields` 直接映射为 row key。Tushare 默认归档。只有明确重新启用时才参与数据链路；大多数 dataset 已经返回 Tushare 风格的标准 key，所以 Mongo 会以相同 `dataset` 名保存原 row。

维护规则：除非明确恢复 Tushare 为支持数据源，否则不要新增 Tushare-only 的标准 key。

## 分钟数据源

分钟数据不以 stock package dataset rows 作为主存储，而是统一写入 `market_data.minute_day_buckets`。

| Source | 使用的上游返回 key | Bucket envelope key | `minutes[]` key |
| --- | --- | --- | --- |
| `pytdx_history` | `price`, `vol`; minute 由 row index 推导 | `source=pytdx_history`, `dataset`, `ts_code`, `symbol`, `trade_date`, `start_minute`, `end_minute`, `row_count`, `fetched_at` | `minute`, `datetime`, `open`, `high`, `low`, `close`, `price`, `volume`, `vol`, `amount`, `amount_estimated=True`, `ohlc_estimated=True` |
| `tdx` / mootdx | `datetime` / date-time, `open`, `high`, `low`, `close`, `volume` / `vol`, `amount` | `source=tdx`, same bucket envelope | `minute`, `datetime`, `open`, `high`, `low`, `close`, `price`, `volume`, `vol`, `amount` |
| `10jqka` latest-day intraday | payload `date`, `name`, `pre`, `marketType`; time rows 拆成 minute, price, amount, avg price, volume | `source=10jqka`, same bucket envelope | `minute`, `datetime`, `market_code`, `name`, `price`, `amount`, `avg_price`, `volume`, `pre_close`, `market_type` |

冷备份 index 只保存 object 和 coverage metadata，不重新映射 minute row key。

## 开盘啦 Market Data

开盘啦数据以 feature-level payload 形态保存到 `market_data.kaipanla_results`。

| Field | 含义 |
| --- | --- |
| `record_id` | 由 feature、保存时间、run ID 生成的稳定 ID |
| `schema` | 当前为 `kaipanla.result.v1` |
| `feature`, `label`, `category` | 来自 `KAIPANLA_FEATURES` 的 feature registry 值 |
| `saved_at`, `run_id`, `path`, `storage`, `synced_at`, `trade_date` | 存储和检索 envelope |
| `ok`, `params` | 运行状态和实际参数 |
| `payload` | raw payload envelope：`{ok, feature, method, params, run_date, result, trade_date?, saved?}` |
| `payload.result` | 数据源原始结果。嵌套 key 有意保留，不逐字段标准化。 |

开盘啦 feature 请求如果遇到上游错误、登录/浏览器依赖缺失、HTTP 失败、空响应或无法解析，应该作为 failed run 暴露，不应保存为 `ok=True` 的空 payload。`run_kaipanla_batch` 负责把单个 feature 异常汇总到 `results[].ok=False`。

开盘啦 daily/scheduled run 会把 `trade_date` 写入 `payload.trade_date` 和 top-level `trade_date`。overview 查询只信任显式日期字段：`trade_date`、`payload.trade_date`、`params.date`、`params.end_date`、`params.trade_date`。实时 feature 如果没有显式交易日，不再用 `saved_at` 推导交易日，避免把盘中实时记录误当成日终数据。

维护规则：如果某个开盘啦 feature 要升级成一张一等标准表，必须先在本文档新增 canonical dataset/table 章节，再改 UI 或 downstream consumer。

## NewsCrawler 原文映射

NewsCrawler 负责新闻采集。DataHub 通过 `MongoRawNewsRepository` 读取 `news.raw_articles`。

| Provider source | Provider raw fields | 标准 `news.raw_articles` key |
| --- | --- | --- |
| Guardian | API item fields，例如 `id`, `webUrl`, section fields, title/body fields | `schema_version`, `article_id`, `source_name`, `external_id`, `source_external_key`, `url`, `canonical_url`, `title`, `summary`, `content`, `published_at`, `fetched_at`, `section`, `language`, `author`, `tags`, `content_hash`, `title_time_hash`, `raw_metadata` |
| Tonghuashun | list/detail fields，例如 article URL, `seq`, title, publish time, content | 同 `news.v1` key |
| Bloomberg | API/browser/article page fields，例如 URL, canonical URL, title, body, publish time | 同 `news.v1` key |
| Politico RSS/browser | RSS `guid`, `link`, title, summary, category, article page fields | 同 `news.v1` key |

`contracts/raw-article.news.v1.schema.json` 是 schema source of truth。必填 key 是 `schema_version`、`article_id`、`source_name`、`url`、`canonical_url`、`title`、`content`、`published_at`、`fetched_at`。Provider 特有细节放入 `raw_metadata`。

## 统一状态

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| Stock package 标准 row | 已统一 | 所有 public stock client 在写 Mongo 前返回相同 dataset 名和标准 key。 |
| Stock package Mongo rows | envelope 已统一，row 原样保留 | `stock_dataset_rows.row` 是标准化 row；top-level Mongo 字段只作为搜索/index envelope。 |
| 财报 raw 字段 | 部分保留 | AkShare 财报 row 保留完整 `raw`，未映射字段可供未来补充。 |
| Daily K 复权口径 | 需要显式关注 | AkShare `stock_zh_a_hist` 当前使用不复权价格；Eastmoney 主 K 线可用时使用复权价格。validator 只补主源缺失字段，不覆盖已有 OHLC；没有明确 `adjust` policy 时，不要替换混合复权和不复权 row。 |
| Market payloads | 未完全统一 | 开盘啦 feature payload 按 feature 保留；只有 downstream consumer 需要稳定字段时才升级为 canonical table。 |
| News | 已统一 | NewsCrawler provider 统一为 `news.v1`；source-specific details 保存在 `raw_metadata`。 |

## 更新 Checklist

新增或修改数据源时：

1. 新增或更新 provider implementation。
2. 在本文档记录每个被使用的上游 key，以及对应的 DataHub target key。
3. 如果 row 会写入 Mongo，写清楚 collection 和 envelope。
4. 如果数据故意保留 raw payload，明确说明。
5. 增加或更新至少一个代表性 mapping test。
6. 重新运行 focused tests 和 `git diff --check`。
