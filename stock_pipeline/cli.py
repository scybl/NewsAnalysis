from __future__ import annotations

import argparse
from pathlib import Path

from .analyst import INITIAL_QUESTION, StockAnalyst, session_path_for
from .collector import StockDataCollector
from .config import PROJECT_ROOT, get_settings
from .deepseek_client import DeepSeekClient
from .dossier import build_dossier
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


def _add_collect_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("code", help="股票代码，例如 000001 或 000001.SZ")
    parser.add_argument("--years", type=int, default=None, help="只回看指定年数；不传则默认抓取全部历史")
    parser.add_argument("--full-history", action="store_true", help="从 1990-01-01 开始尽量抓全历史")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "reports"), help="报告输出根目录")


def run_collect(args: argparse.Namespace) -> Path:
    settings = get_settings(require_deepseek=False)
    ts_code = normalize_ts_code(args.code)
    output_dir = ensure_dir(Path(args.output_dir) / f"{ts_code}_{timestamp()}")
    collector = StockDataCollector(TushareClient(settings.tushare_token, settings.tushare_base_url))
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
