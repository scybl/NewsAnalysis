from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .analyst import INITIAL_QUESTION, StockAnalyst, session_path_for
from .collector import StockDataCollector
from .config import PROJECT_ROOT, get_news_db_config, get_settings
from .deepseek_client import DeepSeekClient
from .dossier import build_dossier
from .news.crawler import CATEGORIES, CrawlOptions, crawl_news, parse_sleep
from .news.storage import Mysql, search_news
from .ths_minute import build_config as build_ths_minute_config
from .ths_minute import fetch_and_store_minutes
from .tushare_client import TushareClient
from .utils import ensure_dir, normalize_ts_code, read_json, timestamp, write_json
from .value_speculation import VALUE_SPECULATION_QUESTION, build_value_speculation_dossier
from .web import serve_web


def main() -> None:
    parser = argparse.ArgumentParser(description="A股个股数据采集与 DeepSeek 连续分析流水线")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect", help="只采集 Tushare 数据并生成 dossier")
    _add_collect_args(collect_parser)

    analyze_parser = subparsers.add_parser("analyze", help="采集数据并调用 DeepSeek 生成分析报告")
    _add_collect_args(analyze_parser)
    analyze_parser.add_argument("--question", default=INITIAL_QUESTION, help="首轮分析问题")
    analyze_parser.add_argument("--stream", action="store_true", help="流式输出 DeepSeek 结果")
    analyze_parser.add_argument("--model", default=None, help="DeepSeek 模型名，默认读取 DEEPSEEK_MODEL 或 deepseek-v4-pro")

    speculate_parser = subparsers.add_parser("speculate", help="采集数据并生成价值投机分析")
    _add_collect_args(speculate_parser)
    speculate_parser.add_argument("--question", default=VALUE_SPECULATION_QUESTION, help="价值投机分析问题")
    speculate_parser.add_argument("--stream", action="store_true", help="流式输出 DeepSeek 结果")
    speculate_parser.add_argument("--model", default=None, help="DeepSeek 模型名")

    chat_parser = subparsers.add_parser("chat", help="基于最近一次分析继续多轮对话")
    chat_parser.add_argument("code", help="股票代码，例如 000001 或 000001.SZ")
    chat_parser.add_argument("--message", "-m", default=None, help="单轮追问；不传则进入交互模式")
    chat_parser.add_argument("--sessions-dir", default=str(PROJECT_ROOT / "sessions"), help="会话保存目录")
    chat_parser.add_argument("--stream", action="store_true", help="流式输出 DeepSeek 结果")
    chat_parser.add_argument("--model", default=None, help="DeepSeek 模型名")

    web_parser = subparsers.add_parser("web", help="启动简单前端")
    web_parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    web_parser.add_argument("--port", type=int, default=8765, help="监听端口")

    news_parser = subparsers.add_parser("news", help="财经新闻抓取和检索")
    news_subparsers = news_parser.add_subparsers(dest="news_command", required=True)
    news_crawl_parser = news_subparsers.add_parser("crawl", help="抓取同花顺财经新闻入库")
    news_crawl_parser.add_argument("--types", default=",".join(CATEGORIES.keys()), help="逗号分隔的分类名称")
    news_crawl_parser.add_argument("--since", default="2019-01-01 00:00:00", help="抓取到该发布时间后停止，格式: YYYY-MM-DD HH:MM:SS")
    news_crawl_parser.add_argument("--max-pages", type=int, default=0, help="每个分类最多抓取页数，0 表示不限制")
    news_crawl_parser.add_argument("--threads", type=int, default=2, help="最大并发分类数")
    news_crawl_parser.add_argument("--article-sleep", type=parse_sleep, default=(2.0, 5.0), help="单篇文章请求间隔，格式: min,max")
    news_crawl_parser.add_argument("--page-sleep", type=parse_sleep, default=(5.0, 15.0), help="分页请求间隔，格式: min,max")
    news_crawl_parser.add_argument("--stale-stop-count", type=int, default=10, help="连续多少篇早于 since 后停止该分类")
    news_crawl_parser.add_argument("--new-only", action="store_true", help="只抓新增文章，连续遇到已存在文章后停止该分类")
    news_crawl_parser.add_argument("--existing-stop-count", type=int, default=10, help="new-only 模式下连续多少篇已存在后停止")
    news_crawl_parser.add_argument("--max-page-failures", type=int, default=3, help="同一分类连续列表页失败多少次后停止")
    news_crawl_parser.add_argument("--dry-run", action="store_true", help="只抓取解析，不写入数据库")
    news_crawl_parser.add_argument("--no-migrate", action="store_true", help="不自动补齐数据库字段和索引")

    news_search_parser = news_subparsers.add_parser("search", help="从本地新闻库检索关键词")
    news_search_parser.add_argument("terms", nargs="+", help="检索关键词，多个关键词按 OR 匹配")
    news_search_parser.add_argument("--limit", type=int, default=20, help="最多返回条数")

    market_parser = subparsers.add_parser("market", help="行情补充数据抓取")
    market_subparsers = market_parser.add_subparsers(dest="market_command", required=True)
    ths_minute_parser = market_subparsers.add_parser("ths-minute", help="抓取指定股票分钟行情到 MongoDB；默认使用通达信/mootdx")
    ths_minute_parser.add_argument("--codes", required=True, help="股票代码，逗号分隔，例如 000001,300033 或 000001.SZ,300033.SZ")
    ths_minute_parser.add_argument("--source", choices=["tdx", "pytdx_history", "ths", "auto"], default="pytdx_history", help="分钟行情源：pytdx_history 为历史分时价量构造分钟 K；tdx 为近期真实分钟 K；ths 为同花顺最新日分时")
    ths_minute_parser.add_argument("--pages", default="all", help="tdx 分页数量；all 表示一直翻到数据源返回空页")
    ths_minute_parser.add_argument("--page-size", type=int, default=800, help="tdx 单页数量，最大 800")
    ths_minute_parser.add_argument("--mongo-db", default=None, help="MongoDB 数据库名，默认 MARKET_MINUTE_DATABASE 或 stock_market")
    ths_minute_parser.add_argument("--collection", default=None, help="MongoDB 集合名，默认 MARKET_MINUTE_COLLECTION 或 tdx_intraday_minutes")
    ths_minute_parser.add_argument("--sleep", type=parse_sleep, default=(0.8, 1.8), help="股票之间请求间隔，格式: min,max")
    ths_minute_parser.add_argument("--timeout", type=float, default=12.0, help="单次请求超时秒数")

    args = parser.parse_args()
    if args.command == "collect":
        run_collect(args)
    elif args.command == "analyze":
        run_analyze(args)
    elif args.command == "speculate":
        run_speculate(args)
    elif args.command == "chat":
        run_chat(args)
    elif args.command == "web":
        serve_web(args.host, args.port)
    elif args.command == "news":
        run_news(args)
    elif args.command == "market":
        run_market(args)


def _add_collect_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("code", help="股票代码，例如 000001 或 000001.SZ")
    parser.add_argument("--years", type=int, default=None, help="只回看指定年数；不传则默认抓取全部历史")
    parser.add_argument("--full-history", action="store_true", help="从 1990-01-01 开始尽量抓全历史")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "reports"), help="报告输出根目录")


def run_collect(args: argparse.Namespace) -> Path:
    settings = get_settings(require_deepseek=False)
    ts_code = normalize_ts_code(args.code)
    output_dir = ensure_dir(Path(args.output_dir) / f"{ts_code}_{timestamp()}")
    collector = StockDataCollector(
        TushareClient(settings.tushare_token, settings.tushare_base_url, pause=settings.tushare_pause_seconds)
    )
    print(f"开始采集 {ts_code}，输出目录：{output_dir}")
    full_data = collector.collect(ts_code, output_dir, years=args.years, full_history=args.full_history or args.years is None)
    dossier = build_dossier(full_data)
    write_json(output_dir / "dossier.json", dossier)
    _print_collect_summary(dossier, output_dir)
    return output_dir


def run_analyze(args: argparse.Namespace) -> None:
    output_dir = run_collect(args)
    settings = get_settings(require_deepseek=True)
    ts_code = normalize_ts_code(args.code)
    dossier = read_json(output_dir / "dossier.json")
    model = args.model or settings.deepseek_model
    analyst = StockAnalyst(DeepSeekClient(settings.deepseek_api_key, settings.deepseek_base_url, model=model))
    session_path = session_path_for(ts_code, PROJECT_ROOT / "sessions")
    print(f"开始调用 DeepSeek（{model}）生成分析...")
    answer = analyst.initial_analysis(dossier, session_path, question=args.question, stream=args.stream)
    (output_dir / "analysis.md").write_text(answer, encoding="utf-8")
    print(f"\n分析完成：{output_dir / 'analysis.md'}")
    print(f"会话已保存：{session_path}")


def run_speculate(args: argparse.Namespace) -> None:
    output_dir = run_collect(args)
    settings = get_settings(require_deepseek=True)
    ts_code = normalize_ts_code(args.code)
    dossier = read_json(output_dir / "dossier.json")
    value_dossier = build_value_speculation_dossier(dossier)
    write_json(output_dir / "value_speculation_dossier.json", value_dossier)

    model = args.model or settings.deepseek_model
    analyst = StockAnalyst(DeepSeekClient(settings.deepseek_api_key, settings.deepseek_base_url, model=model))
    session_path = session_path_for(ts_code, PROJECT_ROOT / "sessions")
    print(f"开始调用 DeepSeek（{model}）生成价值投机分析...")
    answer = analyst.value_speculation_analysis(value_dossier, session_path, question=args.question, stream=args.stream)
    (output_dir / "value_speculation.md").write_text(answer, encoding="utf-8")
    print(f"\n价值投机分析完成：{output_dir / 'value_speculation.md'}")
    print(f"价值投机资料包：{output_dir / 'value_speculation_dossier.json'}")
    print(f"会话已保存：{session_path}")


def run_chat(args: argparse.Namespace) -> None:
    settings = get_settings(require_deepseek=True)
    ts_code = normalize_ts_code(args.code)
    model = args.model or settings.deepseek_model
    analyst = StockAnalyst(DeepSeekClient(settings.deepseek_api_key, settings.deepseek_base_url, model=model))
    session_path = session_path_for(ts_code, Path(args.sessions_dir))

    if args.message:
        answer = analyst.continue_chat(session_path, args.message, stream=args.stream)
        if not args.stream:
            print(answer)
        return

    print(f"进入 {ts_code} 连续对话。输入 exit/quit 结束。")
    while True:
        try:
            user_message = input("\n你：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user_message.lower() in {"exit", "quit", "q"}:
            break
        if not user_message:
            continue
        answer = analyst.continue_chat(session_path, user_message, stream=args.stream)
        if not args.stream:
            print(f"\nDeepSeek：{answer}")


def _print_collect_summary(dossier: dict, output_dir: Path) -> None:
    rows = dossier.get("data_quality", {}).get("dataset_rows", {})
    errors = dossier.get("data_quality", {}).get("fetch_errors", [])
    print("采集完成。主要数据集行数：")
    for name in sorted(rows):
        print(f"  {name}: {rows[name]}")
    if errors:
        print(f"有 {len(errors)} 个接口未成功，已写入 dossier.data_quality.fetch_errors。")
    print(f"dossier：{output_dir / 'dossier.json'}")


def run_news(args: argparse.Namespace) -> None:
    if args.news_command == "crawl":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s")
        options = CrawlOptions(
            types=args.types,
            since=args.since,
            max_pages=args.max_pages,
            threads=args.threads,
            article_sleep=args.article_sleep,
            page_sleep=args.page_sleep,
            stale_stop_count=args.stale_stop_count,
            new_only=args.new_only,
            existing_stop_count=args.existing_stop_count,
            max_page_failures=args.max_page_failures,
            dry_run=args.dry_run,
            migrate=not args.no_migrate,
        )
        result = crawl_news(get_news_db_config(), options)
        print("新闻抓取完成：")
        for kind, stats in result["categories"].items():
            print(f"  {kind}: parsed={stats['parsed']} inserted={stats['inserted']} skipped={stats['skipped']}")
        return

    if args.news_command == "search":
        with Mysql(get_news_db_config()) as mysql:
            rows = search_news(mysql, args.terms, limit=args.limit)
        for row in rows:
            print(f"{row.get('time')} [{row.get('type')}] {row.get('title')}")
            if row.get("url"):
                print(f"  {row.get('url')}")


def run_market(args: argparse.Namespace) -> None:
    if args.market_command == "ths-minute":
        codes = [item.strip() for item in args.codes.split(",") if item.strip()]
        if not codes:
            raise ValueError("请通过 --codes 传入至少一个股票代码。")
        config = build_ths_minute_config(database=args.mongo_db, collection=args.collection, timeout=args.timeout)
        result = fetch_and_store_minutes(codes, config=config, sleep_range=args.sleep, source=args.source, pages=args.pages, page_size=args.page_size)
        print(f"分钟行情抓取完成：{result['database']}.{result['collection']} source={result.get('source')}")
        for item in result["results"]:
            if item.get("ok"):
                print(
                    f"  {item['ts_code']} {item.get('name') or ''} "
                    f"{item.get('date_range', {}).get('start') or item.get('trade_date')}..{item.get('date_range', {}).get('end') or item.get('trade_date')} "
                    f"dataset={item.get('dataset')} rows={item['rows']} inserted={item['inserted']} updated={item['updated']}"
                )
            else:
                print(f"  {item['ts_code']}: 失败：{item.get('error')}")
