# News Spider

一个新闻爬虫集合。当前包含：

- 同花顺财经新闻爬虫，默认写入 MongoDB。
- `newsweaver/` 下的 Bloomberg 和 Guardian 爬虫，来自 NewsWeaver 仓库，已移入本目录并去掉本地 `.env` 配置文件。

## Dependency

```bash
pip install -r requirements.txt
```

旧文件名仍保留兼容：

```bash
pip install -r requirments.txt
```

## Database

默认写入 MongoDB 的 `news.articles`。敏感连接信息不要写入 `.env`，请在项目根目录使用统一加密密钥库：

```bash
.venv/bin/python -m stock_pipeline secrets set mongo.password
```

非敏感库名和集合名仍可用环境变量覆盖：

```bash
export MONGO_HOST=localhost
export MONGO_PORT=27017
export MONGO_DB=news
export MONGO_COLLECTION=articles
export MONGO_USER=admin
export MONGO_AUTHSOURCE=admin
export MONGODB_DATABASE=news
export MONGODB_COLLECTION=articles
```

首次运行会自动创建索引：

- `seq` 唯一稀疏索引
- `url` 唯一稀疏索引
- `title` 普通稀疏索引
- `time`、`type + time`、`publisher + time` 查询索引

## Usage

低频测试一页，不写数据库：

```bash
python main.py --types 财经要闻 --max-pages 1 --dry-run
```

抓取指定分类和页数：

```bash
python main.py --types 财经要闻,金融市场 --max-pages 3
```

按时间增量抓取：

```bash
python main.py --since "2026-06-01 00:00:00" --max-pages 5
```

只抓新增文章，连续遇到已存在文章后停止：

```bash
python main.py --types 财经要闻 --new-only --existing-stop-count 10
```

降低请求频率：

```bash
python main.py --threads 1 --article-sleep 3,8 --page-sleep 10,30
```

## Current Categories

- 财经要闻
- 宏观经济
- 产经新闻
- 国际财经
- 金融市场
- 公司新闻
- 区域经济
- 财经评论
- 财经人物

## Notes

- 数据按 `seq` 优先去重，缺少 `seq` 时回退到 `url` 和 `title`。
- `--new-only` 适合日常定时运行，能在连续遇到旧文章后尽早停止，减少请求量。
- 首次运行会自动创建 MongoDB 索引；如需关闭，使用 `--no-migrate`。
- 日志默认写入 `logs/spider.log`。
- 建议低频、少页数运行，仅用于学习和个人研究。

## NewsWeaver

NewsWeaver 已放到 `newsweaver/`：

- `newsweaver/Bloomberg/get_url/`：获取 Bloomberg 最新文章 URL，写入 MongoDB URL 队列。
- `newsweaver/Bloomberg/final_article/`：读取 URL 队列并抓取 Bloomberg 正文。
- `newsweaver/Guardian/`：通过 Guardian Content API 抓取 Guardian 文章。
- `newsweaver/schedule.txt`：原 Windows 定时任务安排。
- `newsweaver/demo/`：文章数量统计静态 dashboard。

这些脚本继续使用 MongoDB，并会读取项目根目录 `.env`。运行前请按各子目录 README 或根目录 `.env.sample` 配置环境变量，例如 `MONGODB_DATABASE`、`MONGODB_COLLECTION`、`MONGO_*`、`SSH_*`、`GUARDIAN_API_KEY` 等。
