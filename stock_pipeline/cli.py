from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
from typing import Any

from .analyst import INITIAL_QUESTION, StockAnalyst, session_path_for
from .akshare_client import AkshareClient
from .composite_client import FallbackStockClient
from .collector import StockDataCollector
from .config import PROJECT_ROOT, get_settings
from .deepseek_client import DeepSeekClient
from .dossier import build_dossier
from .kaipanla import (
    list_kaipanla_features,
    list_kaipanla_records,
    parse_params,
    repair_kaipanla_overview_history,
    run_kaipanla_batch,
    run_kaipanla_feature,
    validate_kaipanla_integration,
)
from .market_dimensions import MARKET_COLLECTIONS, MARKET_DATABASE
from .minute_cold_storage import archive_buckets as archive_minute_buckets
from .minute_cold_storage import archive_month_shards as archive_minute_month_shards
from .minute_cold_storage import archive_stock_shards as archive_minute_stock_shards
from .minute_cold_storage import build_config as build_minute_cold_config
from .minute_cold_storage import cleanup_archived_buckets as cleanup_minute_archived_buckets
from .minute_cold_storage import ensure_indexes as ensure_minute_cold_indexes
from .minute_cold_storage import prune_cache as prune_minute_cache
from .minute_cold_storage import read_cached_or_downloaded_day
from .news_library import query_news_library
from .secret_store import SECRET_ENV_MAP, get_secret_store
from .ths_minute import build_config as build_ths_minute_config
from .ths_minute import fetch_and_store_minutes
from .totp import generate_totp_secret, normalize_totp_secret, otpauth_uri
from .tushare_client import TushareClient
from .tushare_kline import KlineBackfillConfig, fetch_all_stock_klines
from .utils import ensure_dir, normalize_ts_code, read_json, timestamp, write_json
from .value_speculation import VALUE_SPECULATION_QUESTION, build_value_speculation_dossier
from .web import serve_web


def parse_sleep(value: str) -> tuple[float, float]:
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 2 or parts[0] < 0 or parts[1] < parts[0]:
        raise argparse.ArgumentTypeError("sleep range must be formatted as min,max")
    return parts[0], parts[1]


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

    secrets_parser = subparsers.add_parser("secrets", help="管理本地加密密钥库，不把 key 写入 .env")
    secrets_subparsers = secrets_parser.add_subparsers(dest="secrets_command", required=True)
    secrets_subparsers.add_parser("list", help="列出已配置的密钥名，不显示明文")
    secrets_set_parser = secrets_subparsers.add_parser("set", help="写入一个密钥，默认从安全输入读取")
    secrets_set_parser.add_argument("name", help="密钥名，例如 tushare.api_token、web.admin_password、guardian.api_key")
    secrets_set_parser.add_argument("--value", default=None, help="直接传入值；不推荐在共享机器上使用，可能进入 shell 历史")
    secrets_delete_parser = secrets_subparsers.add_parser("delete", help="删除一个密钥")
    secrets_delete_parser.add_argument("name", help="密钥名")
    secrets_subparsers.add_parser("migrate-env", help="把当前 .env/环境变量中的敏感项迁入加密密钥库")
    setup_totp_parser = secrets_subparsers.add_parser("setup-admin-totp", help="生成并保存管理员 Authenticator 一次性验证码密钥")
    setup_totp_parser.add_argument("--account", default=None, help="Authenticator 中显示的账号名，默认读取管理员账号")
    setup_totp_parser.add_argument("--issuer", default="NewsAnalysis", help="Authenticator 中显示的发行方")
    setup_totp_parser.add_argument("--secret", default=None, help="使用已有 Base32 密钥；不传则自动生成")

    news_parser = subparsers.add_parser("news", help="检索由独立 NewsCrawler 写入的新闻")
    news_subparsers = news_parser.add_subparsers(dest="news_command", required=True)
    news_search_parser = news_subparsers.add_parser("search", help="从本地新闻库检索关键词")
    news_search_parser.add_argument("terms", nargs="+", help="检索关键词，多个关键词按 OR 匹配")
    news_search_parser.add_argument("--limit", type=int, default=20, help="最多返回条数")

    market_parser = subparsers.add_parser("market", help="行情补充数据抓取")
    market_subparsers = market_parser.add_subparsers(dest="market_command", required=True)
    tushare_kline_parser = market_subparsers.add_parser("tushare-kline", help="使用 Tushare 批量抓取全市场 K 线价量数据")
    tushare_kline_parser.add_argument("--start-date", default="19900101", help="开始日期，格式 YYYYMMDD")
    tushare_kline_parser.add_argument("--end-date", default="", help="结束日期，默认今天")
    tushare_kline_parser.add_argument("--freq", default="daily", help="K 线频率，逗号分隔：daily,weekly,monthly")
    tushare_kline_parser.add_argument("--codes", default="", help="只抓指定股票，逗号分隔；不传则抓全部上市 A 股")
    tushare_kline_parser.add_argument("--include-delisted", action="store_true", help="同时包含退市和暂停上市股票")
    tushare_kline_parser.add_argument("--force", action="store_true", help="即使本地已有覆盖日期范围的数据也重新抓取")
    tushare_kline_parser.add_argument("--limit", type=int, default=None, help="最多抓取多少只股票，适合先小批量验证")
    tushare_kline_parser.add_argument("--workers", type=int, default=1, help="并发抓取股票数，建议 2-4，过高可能触发 Tushare 限流")
    tushare_kline_parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "local_data" / "tushare_kline"), help="输出目录")
    ths_minute_parser = market_subparsers.add_parser("ths-minute", help="抓取指定股票分钟行情到 MongoDB；默认使用通达信/mootdx")
    ths_minute_parser.add_argument("--codes", required=True, help="股票代码，逗号分隔，例如 000001,300033 或 000001.SZ,300033.SZ")
    ths_minute_parser.add_argument("--source", choices=["tdx", "pytdx_history", "ths", "auto"], default="pytdx_history", help="分钟行情源：pytdx_history 为历史分时价量构造分钟 K；tdx 为近期真实分钟 K；ths 为同花顺最新日分时")
    ths_minute_parser.add_argument("--pages", default="all", help="tdx 分页数量；all 表示一直翻到数据源返回空页")
    ths_minute_parser.add_argument("--page-size", type=int, default=800, help="tdx 单页数量，最大 800")
    ths_minute_parser.add_argument("--mongo-db", default=None, help="MongoDB 数据库名，默认 MARKET_MINUTE_DATABASE 或 market_data")
    ths_minute_parser.add_argument("--collection", default=None, help="MongoDB 集合名，默认 MARKET_MINUTE_COLLECTION 或 minute_day_buckets")
    ths_minute_parser.add_argument("--sleep", type=parse_sleep, default=(0.8, 1.8), help="股票之间请求间隔，格式: min,max")
    ths_minute_parser.add_argument("--timeout", type=float, default=12.0, help="单次请求超时秒数")
    minute_cold_parser = market_subparsers.add_parser("minute-cold", help="归档、上传和按需取回股票分钟冷数据")
    minute_cold_parser.add_argument("action", choices=["export", "export-upload", "export-month-upload", "export-stock-upload", "cleanup-archived", "retrieve", "prune-cache"], help="export 只写本地对象和索引；export-stock-upload 按股票整包同步；cleanup-archived 清理已归档旧 bucket；retrieve 单日取回缓存")
    minute_cold_parser.add_argument("--codes", default="", help="股票代码，逗号分隔；不传则处理全部")
    minute_cold_parser.add_argument("--source", default="pytdx_history", help="数据源，默认 pytdx_history")
    minute_cold_parser.add_argument("--trade-date", default="", help="交易日 YYYYMMDD；retrieve 必填，export 可选")
    minute_cold_parser.add_argument("--limit", type=int, default=None, help="最多处理多少个股票日 bucket，适合先小批量验证")
    minute_cold_parser.add_argument("--workers", type=int, default=1, help="export-month-upload 并发上传月分片数，建议 2-4")
    minute_cold_parser.add_argument("--execute", action="store_true", help="cleanup-archived 默认只 dry-run；传入该参数才真正删除")
    minute_cold_parser.add_argument("--mongo-db", default=None, help="MongoDB 数据库名，默认 market_data")
    minute_cold_parser.add_argument("--collection", default=None, help="分钟 bucket 集合名，默认 minute_day_buckets")

    kaipanla_parser = subparsers.add_parser("kaipanla", help="开盘啦数据源")
    kaipanla_subparsers = kaipanla_parser.add_subparsers(dest="kaipanla_command", required=True)
    kaipanla_subparsers.add_parser("list", help="列出已集成的开盘啦功能")
    kaipanla_subparsers.add_parser("validate", help="验证开盘啦功能映射是否覆盖全部公开方法")
    kaipanla_subparsers.add_parser("records", help="列出已保存的开盘啦抓取记录")
    kaipanla_run_parser = kaipanla_subparsers.add_parser("run", help="运行一个开盘啦功能")
    kaipanla_run_parser.add_argument("feature", help="功能 key，可先运行 kaipanla list 查看")
    kaipanla_run_parser.add_argument("--params", default="", help='JSON 参数，例如 {"date":"2026-01-16"}')
    kaipanla_run_parser.add_argument("--save", action="store_true", help="把运行结果保存到 MongoDB")
    kaipanla_batch_parser = kaipanla_subparsers.add_parser("batch", help="批量运行多个开盘啦功能并保存")
    kaipanla_batch_parser.add_argument("--features", required=True, help="逗号分隔功能 key")
    kaipanla_batch_parser.add_argument("--params", default="", help="JSON object，key 为功能 key，value 为该功能参数")
    kaipanla_repair_parser = kaipanla_subparsers.add_parser("repair-overview", help="重抓并修正某交易日市场纵览异常历史记录")
    kaipanla_repair_parser.add_argument("--date", required=True, help="交易日，例如 2026-06-30")
    kaipanla_repair_parser.add_argument("--dry-run", action="store_true", help="只核对实时返回和待归档数量，不写入 MongoDB")

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
    elif args.command == "secrets":
        run_secrets(args)
    elif args.command == "news":
        run_news(args)
    elif args.command == "market":
        run_market(args)
    elif args.command == "kaipanla":
        run_kaipanla(args)


def _add_collect_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("code", help="股票代码，例如 000001 或 000001.SZ")
    parser.add_argument("--years", type=int, default=None, help="只回看指定年数；不传则默认抓取全部历史")
    parser.add_argument("--full-history", action="store_true", help="从 1990-01-01 开始尽量抓全历史")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "reports"), help="报告输出根目录")


def run_secrets(args: argparse.Namespace) -> None:
    from .config import load_dotenv

    load_dotenv()
    store = get_secret_store()
    if args.secrets_command == "list":
        states = store.list_states()
        if not states:
            print("尚未配置任何加密密钥。")
            print("常用密钥名：" + "、".join(sorted(SECRET_ENV_MAP)))
            return
        for name, state in states.items():
            mark = "已配置" if state.configured else "未配置"
            suffix = f"；更新时间：{state.updated_at}" if state.updated_at else ""
            print(f"{name}: {mark}{suffix}")
        return
    if args.secrets_command == "set":
        value = args.value
        if value is None:
            value = getpass.getpass(f"{args.name}: ")
        store.set(args.name, value, updated_by="cli")
        print(f"{args.name}: 已加密保存。")
        return
    if args.secrets_command == "delete":
        deleted = store.delete(args.name)
        print(f"{args.name}: {'已删除' if deleted else '原本未配置'}。")
        return
    if args.secrets_command == "migrate-env":
        migrated = store.migrate_from_env()
        if migrated:
            print("已迁移：" + "、".join(migrated))
            print("确认服务可启动后，可以从 .env 删除这些敏感项。")
        else:
            print("没有发现需要迁移的 env 敏感项，或密钥库中已存在对应值。")
        return
    if args.secrets_command == "setup-admin-totp":
        username = args.account or store.get("web.admin_username", "admin")
        secret = normalize_totp_secret(args.secret or generate_totp_secret())
        store.set("web.admin_totp_secret", secret, updated_by="cli")
        print("管理员 Authenticator 已启用。")
        print("请在 Google/Microsoft/Authy 等 Authenticator 中添加以下 URI，或手动输入密钥。")
        print(f"账号：{username}")
        print(f"手动密钥：{secret}")
        print(f"otpauth URI：{otpauth_uri(secret, account=username, issuer=args.issuer)}")
        print("添加完成后，管理员登录需要账号、密码和 30 秒一次性验证码。")
        return


def run_collect(args: argparse.Namespace) -> Path:
    settings = get_settings(require_deepseek=False)
    ts_code = normalize_ts_code(args.code)
    output_dir = ensure_dir(Path(args.output_dir) / f"{ts_code}_{timestamp()}")
    collector = StockDataCollector(
        FallbackStockClient(
            TushareClient(settings.tushare_token, settings.tushare_base_url, pause=settings.tushare_pause_seconds),
            [AkshareClient(pause=settings.tushare_pause_seconds)],
        )
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
    if args.news_command == "search":
        result = query_news_library({"q": [" ".join(args.terms)], "page_size": [str(args.limit)], "days": ["0"]})
        if not result.get("enabled"):
            raise RuntimeError(f"本地新闻库不可用：{result.get('error') or 'unknown error'}")
        rows = result.get("items", [])
        for row in rows:
            print(f"{row.get('time')} [{row.get('type')}] {row.get('title')}")
            if row.get("url"):
                print(f"  {row.get('url')}")


def run_market(args: argparse.Namespace) -> None:
    if args.market_command == "tushare-kline":
        settings = get_settings(require_deepseek=False)
        if not settings.tushare_token:
            raise RuntimeError("缺少 Tushare token。请先运行：.venv/bin/python -m stock_pipeline secrets set tushare.api_token")
        frequencies = tuple(item.strip() for item in args.freq.split(",") if item.strip())
        codes = tuple(item.strip() for item in args.codes.split(",") if item.strip())
        result = fetch_all_stock_klines(
            TushareClient(settings.tushare_token, settings.tushare_base_url, pause=settings.tushare_pause_seconds),
            KlineBackfillConfig(
                output_dir=Path(args.output_dir),
                start_date=args.start_date,
                end_date=args.end_date,
                frequencies=frequencies,
                include_delisted=args.include_delisted,
                force=args.force,
                limit=args.limit,
                codes=codes,
                progress=True,
                workers=args.workers,
            ),
        )
        print(
            f"Tushare K 线抓取完成：stocks={result['stock_count']} "
            f"updated={result['updated']} skipped={result['skipped']} failed={result['failed']} rows={result['rows']}"
        )
        print(f"manifest：{Path(result['output_dir']) / 'manifest.json'}")
        return
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
        return
    if args.market_command == "minute-cold":
        run_minute_cold(args)
        return


def run_minute_cold(args) -> None:
    try:
        import pymongo
    except ImportError as exc:
        raise RuntimeError("缺少 pymongo，无法连接 MongoDB。") from exc

    database = args.mongo_db or MARKET_DATABASE
    collection_name = args.collection or MARKET_COLLECTIONS["minute_buckets"]
    config = build_minute_cold_config()
    mongo_config = build_ths_minute_config(database=database, collection=collection_name)
    client = pymongo.MongoClient(mongo_config.mongo_uri, serverSelectionTimeoutMS=8000)
    try:
        db = client[database]
        buckets = db[collection_name]
        day_index = db[MARKET_COLLECTIONS["minute_day_index"]]
        coverage = db[MARKET_COLLECTIONS["minute_coverage"]]
        ensure_minute_cold_indexes(day_index, coverage, pymongo)
        if args.action in {"export", "export-upload"}:
            query: dict[str, Any] = {"source": args.source}
            codes = [normalize_ts_code(item.strip()) for item in args.codes.split(",") if item.strip()]
            if codes:
                query["ts_code"] = {"$in": codes}
            if args.trade_date:
                query["trade_date"] = args.trade_date.replace("-", "")
            result = archive_minute_buckets(
                buckets,
                day_index,
                coverage,
                query=query,
                config=config,
                limit=args.limit,
                upload=args.action == "export-upload",
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return
        if args.action == "export-month-upload":
            query = {"source": args.source}
            codes = [normalize_ts_code(item.strip()) for item in args.codes.split(",") if item.strip()]
            if codes:
                query["ts_code"] = {"$in": codes}
            if args.trade_date:
                trade_date = args.trade_date.replace("-", "")
                query["trade_date"] = {"$regex": f"^{trade_date[:6]}"}
            result = archive_minute_month_shards(
                buckets,
                day_index,
                coverage,
                query=query,
                config=config,
                limit=args.limit,
                upload=True,
                workers=args.workers,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return
        if args.action == "export-stock-upload":
            query = {"source": args.source}
            codes = [normalize_ts_code(item.strip()) for item in args.codes.split(",") if item.strip()]
            if codes:
                query["ts_code"] = {"$in": codes}
            result = archive_minute_stock_shards(
                buckets,
                day_index,
                coverage,
                query=query,
                config=config,
                limit=args.limit,
                upload=True,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return
        if args.action == "cleanup-archived":
            codes = [normalize_ts_code(item.strip()) for item in args.codes.split(",") if item.strip()]
            result = cleanup_minute_archived_buckets(
                buckets,
                day_index,
                coverage,
                source=args.source,
                hot_days=config.hot_days,
                codes=codes,
                dry_run=not args.execute,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return
        if args.action == "retrieve":
            if not args.codes or not args.trade_date:
                raise ValueError("retrieve 需要 --codes 单只股票和 --trade-date。")
            ts_code = normalize_ts_code(args.codes.split(",", 1)[0].strip())
            rows = read_cached_or_downloaded_day(
                day_index,
                ts_code=ts_code,
                trade_date=args.trade_date,
                source=args.source,
                config=config,
            )
            print(json.dumps({"ok": True, "ts_code": ts_code, "trade_date": args.trade_date, "rows": len(rows)}, ensure_ascii=False, indent=2))
            return
        if args.action == "prune-cache":
            result = prune_minute_cache(config.cache_root, config.cache_max_bytes)
            print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
            return
    finally:
        client.close()


def run_kaipanla(args: argparse.Namespace) -> None:
    if args.kaipanla_command == "list":
        for item in list_kaipanla_features():
            suffix = f"；需要：{item['requires']}" if item.get("requires") else ""
            print(f"{item['key']}\t{item['category']}\t{item['label']}{suffix}")
        return
    if args.kaipanla_command == "validate":
        result = validate_kaipanla_integration()
        print(f"features={result['feature_count']} public_methods={result['method_count']} ok={result['ok']}")
        if result["missing_methods"]:
            print("未映射方法：" + "、".join(result["missing_methods"]))
        if result["unknown_methods"]:
            print("未知方法：" + "、".join(result["unknown_methods"]))
        return
    if args.kaipanla_command == "records":
        import json

        print(json.dumps(list_kaipanla_records(), ensure_ascii=False, indent=2))
        return
    if args.kaipanla_command == "run":
        import json

        result = run_kaipanla_feature(args.feature, parse_params(args.params), save=args.save)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.kaipanla_command == "batch":
        import json

        features = [item.strip() for item in args.features.split(",") if item.strip()]
        result = run_kaipanla_batch(features, parse_params(args.params), save=True, run_id=timestamp())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.kaipanla_command == "repair-overview":
        import json

        result = repair_kaipanla_overview_history(args.date, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
