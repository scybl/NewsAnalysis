from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pymongo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stock_pipeline.data_random_audit import build_random_audit_payload
from stock_pipeline.market_dimensions import MARKET_COLLECTIONS, MARKET_DATABASE
from stock_pipeline.ths_minute import build_config as build_mongo_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run read-mostly random health checks over server data.")
    parser.add_argument("--output", default="", help="Write Markdown report to this path. Defaults to stdout only.")
    parser.add_argument("--json-output", default="", help="Write JSON payload to this path.")
    parser.add_argument("--json", action="store_true", help="Print JSON payload after Markdown.")
    parser.add_argument("--sample-size", type=int, default=20, help="Random samples per data family. Default: 20.")
    parser.add_argument("--seed", type=int, default=None, help="Fixed random seed for reproducible sampling.")
    parser.add_argument("--cold-read-samples", type=int, default=0, help="How many minute cold objects to download/read. Default: 0.")
    parser.add_argument("--quiet", action="store_true", help="Do not print progress messages to stderr.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    progress = Progress(enabled=not args.quiet)
    progress("连接 MongoDB")
    config = build_mongo_config(database=MARKET_DATABASE, collection=MARKET_COLLECTIONS["minute_buckets"])
    client = pymongo.MongoClient(config.mongo_uri, serverSelectionTimeoutMS=8000)
    try:
        payload = build_random_audit_payload(
            client,
            sample_size=args.sample_size,
            seed=args.seed,
            cold_read_samples=args.cold_read_samples,
            progress=progress,
        )
    finally:
        client.close()

    progress("渲染 Markdown 报告")
    markdown = render_markdown(payload)
    print(markdown)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown + "\n", encoding="utf-8")
        progress(f"写入 Markdown：{args.output}")
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        progress(f"写入 JSON：{args.json_output}")
    if args.json:
        print("\n```json")
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        print("```")
    return 0 if payload.get("ok") else 2


class Progress:
    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self.step = 0

    def __call__(self, message: str) -> None:
        if not self.enabled:
            return
        self.step += 1
        print(f"[server-data-random-audit] {self.step}. {message}", file=sys.stderr, flush=True)


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# 服务器数据随机抽检报告",
        "",
        f"- 生成时间：`{payload.get('generated_at', '')}`",
        f"- 随机种子：`{payload.get('seed', '')}`",
        f"- 每类抽样数：`{payload.get('sample_size', '')}`",
        f"- 冷备份取回样本：`{payload.get('cold_read_samples', 0)}`",
        f"- 总体状态：`{status_label(summary.get('status'))}`",
        f"- 检查项：`{summary.get('checks', 0)}`，正常 `{summary.get('ok_checks', 0)}`，警告 `{summary.get('warning_checks', 0)}`，危险 `{summary.get('danger_checks', 0)}`，异常 `{summary.get('anomalies', 0)}`",
        "",
        "## 检查结果",
        "",
        "| 检查项 | 检查内容 | 状态 | 异常数 | 关键指标 |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for check in payload.get("checks") or []:
        lines.append(
            "| {title} | {description} | {status} | {count} | {metrics} |".format(
                title=escape_cell(check.get("title") or ""),
                description=escape_cell(check.get("description") or ""),
                status=status_label(check.get("status")),
                count=int((check.get("summary") or {}).get("anomalies") or 0),
                metrics=escape_cell(short_metrics(check.get("metrics") or {})),
            )
        )

    lines.extend(["", "## 异常明细", ""])
    had_anomaly = False
    for check in payload.get("checks") or []:
        anomalies = check.get("anomalies") or []
        if not anomalies:
            continue
        had_anomaly = True
        lines.extend([f"### {check.get('title')}", ""])
        for item in anomalies[:50]:
            lines.append(f"- `{item.get('severity', '')}` `{item.get('code', '')}` {item.get('message', '')}：`{compact_json(item)}`")
        lines.append("")
    if not had_anomaly:
        lines.append("未发现异常。")

    lines.extend(["", "## 抽样明细", ""])
    for check in payload.get("checks") or []:
        details = check.get("details") or []
        if not details:
            continue
        lines.extend([f"### {check.get('title')}", ""])
        for item in details[:30]:
            lines.append(f"- `{compact_json(item)}`")
        lines.append("")
    return "\n".join(lines).rstrip()


def short_metrics(metrics: dict[str, Any]) -> str:
    items = []
    for key, value in list(metrics.items())[:6]:
        if isinstance(value, (dict, list)):
            continue
        items.append(f"{key}={value}")
    return "；".join(items)


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def status_label(status: Any) -> str:
    return {"ok": "正常", "warning": "警告", "danger": "危险"}.get(str(status or ""), str(status or "未知"))


def escape_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
