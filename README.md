# Tushare Stock Analysis Pipeline

一个面向 A 股个股研究的流水线工程：输入股票代码，自动从 Tushare Pro 拉取行情、估值、财务、公司、行业、公告等数据，整理成结构化 dossier，然后调用 DeepSeek 生成可持续追问的分析对话。

## 快速开始

`.env` 支持以下变量名：

```bash
TUSHARE_API=你的TushareToken
DEEPSEEK_API=你的DeepSeekKey
STOCK_WEB_USER=admin
STOCK_WEB_PASSWORD=请换成强密码
STOCK_WEB_SESSION_SECRET=一段随机字符串
```

也兼容 `TUSHARE_TOKEN` 和 `DEEPSEEK_API_KEY`。

运行一次完整分析：

```bash
python3 -m stock_pipeline analyze 000001.SZ
```

只采集数据，不调用 DeepSeek：

```bash
python3 -m stock_pipeline collect 000001
```

默认会从 1990-01-01 开始尽量抓取全部历史数据；如果只想更新最近几年，可以加 `--years 8` 这类参数。

基于最近一次分析继续对话：

```bash
python3 -m stock_pipeline chat 000001.SZ
```

启动简单前端：

```bash
python3 -m stock_pipeline web
```

然后打开 `http://127.0.0.1:8765`，可以用股票代码、名称、首字母或拼音检索，例如 `000001`、`平安银行`、`mygf`、`muyuangufen`。

前端默认启用账号密码登录。若未配置，默认账号密码为 `admin/admin`，只适合本地测试；部署到服务器前请务必在 `.env` 中设置 `STOCK_WEB_USER`、`STOCK_WEB_PASSWORD` 和 `STOCK_WEB_SESSION_SECRET`。

如果希望全市场股票名称的拼音/首字母检索更完整，建议安装：

```bash
pip install -r requirements.txt
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
