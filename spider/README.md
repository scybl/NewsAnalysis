# TongHuaShun-Spider

一个同花顺财经新闻爬虫。

## Dependency

```bash
pip install -r requirements.txt
```

旧文件名仍保留兼容：

```bash
pip install -r requirments.txt
```

## Database

默认读取 `localhost:3306 / root / root / news`，可以通过环境变量覆盖：

```bash
export MYSQL_HOST=localhost
export MYSQL_PORT=3306
export MYSQL_USER=root
export MYSQL_PASSWORD=root
export MYSQL_DATABASE=news
```

初始化数据库：

```bash
mysql -u root -p < news.sql
```

如果使用本次创建的临时 MySQL：

```bash
export MYSQL_PORT=3307
export MYSQL_PASSWORD=
```

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
- 首次运行会自动补齐旧数据库缺少的字段和索引；如需关闭，使用 `--no-migrate`。
- 日志默认写入 `logs/spider.log`。
- 建议低频、少页数运行，仅用于学习和个人研究。
