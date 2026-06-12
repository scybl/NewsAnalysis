from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .deepseek_client import DeepSeekClient
from .utils import ensure_dir, read_json, write_json
from .analysis_frameworks import AnalysisFramework
from .value_speculation import VALUE_SPECULATION_QUESTION


SYSTEM_PROMPT = """你是一个严谨的 A 股股票研究助手。你会基于用户提供的 Tushare 结构化数据分析，不编造不存在的数据。

输出要求：
1. 用中文回答，先给结论，再给证据链。
2. 区分短期走势、中期基本面、长期不确定性，不承诺确定收益。
3. 明确指出支撑因素、风险因素、需要继续跟踪的指标。
4. 如果数据缺失或接口权限不足，要说明缺口如何影响判断。
5. 这不是投资建议，不能直接要求用户买入/卖出，只能给研究观点和情景推演。
"""


INITIAL_QUESTION = """请基于这份 Tushare 个股资料包，生成一份股票分析：
- 公司和行业处在什么位置
- 最近价格/成交/估值表现
- 财务质量和趋势
- 股东、资金流、公告中有哪些信号
- 未来可能的上行/中性/下行情景
- 后续最值得跟踪的 5 个指标
"""


VALUE_SPECULATION_SYSTEM_PROMPT = """你是一个严谨的 A 股“价值投机”研究助手。

你的分析方法：
1. 先用价值框架判断公司是否有基本面底线和安全边际。
2. 再用行业周期、催化事件、资金面和技术趋势判断是否存在更好的交易窗口。
3. 你关注的是赔率和条件，不做确定性预测，也不直接给买入/卖出指令。

输出纪律：
- 只能基于用户提供的数据，不编造缺失数据。
- 每个判断都要尽量对应资料包中的证据。
- 必须区分“价值基础”和“投机触发”。
- 必须写出什么信号会证伪当前逻辑。
- 这不是投资建议，只是研究和交易计划辅助。
"""


class ConversationStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        payload = read_json(self.path)
        return payload.get("messages", [])

    def save(self, messages: list[dict[str, str]], metadata: dict[str, Any] | None = None) -> None:
        write_json(self.path, {"metadata": metadata or {}, "messages": messages})


class StockAnalyst:
    def __init__(self, client: DeepSeekClient):
        self.client = client

    def initial_analysis(
        self,
        dossier: dict[str, Any],
        session_path: Path,
        question: str = INITIAL_QUESTION,
        stream: bool = False,
    ) -> str:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{question}\n\n资料包 JSON：\n{json.dumps(dossier, ensure_ascii=False)}"},
        ]
        answer = self.client.chat(messages, stream=stream)
        messages.append({"role": "assistant", "content": answer})
        ConversationStore(session_path).save(messages, {"ts_code": dossier.get("ts_code")})
        return answer

    def value_speculation_analysis(
        self,
        value_dossier: dict[str, Any],
        session_path: Path,
        question: str = VALUE_SPECULATION_QUESTION,
        stream: bool = False,
    ) -> str:
        messages = [
            {"role": "system", "content": VALUE_SPECULATION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"{question}\n\n价值投机资料包 JSON：\n{json.dumps(value_dossier, ensure_ascii=False)}",
            },
        ]
        answer = self.client.chat(messages, stream=stream)
        messages.append({"role": "assistant", "content": answer})
        ConversationStore(session_path).save(
            messages,
            {
                "ts_code": value_dossier.get("ts_code"),
                "framework": "value_speculation",
                "rating_hint": value_dossier.get("decision_helper", {}).get("rating_hint"),
            },
        )
        return answer

    def framework_analysis(
        self,
        analysis_dossier: dict[str, Any],
        session_path: Path,
        framework: AnalysisFramework,
        question: str | None = None,
        stream: bool = False,
        historical_context: str = "",
    ) -> str:
        prompt = question or framework.question
        review_instruction = ""
        if historical_context:
            review_instruction = (
                "\n\n历史分析复盘材料：\n"
                f"{historical_context}\n\n"
                "请先对这些历史分析做复盘：\n"
                "1. 哪些判断被最新数据支持；\n"
                "2. 哪些判断可能已经被证伪或需要降权；\n"
                "3. 本次结论相较过去应如何调整，原因是什么。\n"
                "如果历史材料不足以复盘，请明确说明不可判断，不要硬凑。"
            )
        messages = [
            {"role": "system", "content": framework.system_prompt},
            {
                "role": "user",
                "content": f"{prompt}{review_instruction}\n\n{framework.label}资料包 JSON：\n{json.dumps(analysis_dossier, ensure_ascii=False)}",
            },
        ]
        answer = self.client.chat(messages, stream=stream)
        messages.append({"role": "assistant", "content": answer})
        ConversationStore(session_path).save(
            messages,
            {
                "ts_code": analysis_dossier.get("ts_code"),
                "framework": framework.key,
                "framework_label": framework.label,
                "rating_hint": analysis_dossier.get("decision_helper", {}).get("rating_hint"),
            },
        )
        return answer

    def continue_chat(
        self,
        session_path: Path,
        user_message: str,
        stream: bool = False,
    ) -> str:
        store = ConversationStore(session_path)
        messages = store.load()
        if not messages:
            raise RuntimeError("没有找到已有会话。请先运行 analyze，或指定已有 session 文件。")
        messages.append({"role": "user", "content": user_message})
        answer = self.client.chat(messages, stream=stream)
        messages.append({"role": "assistant", "content": answer})
        store.save(messages)
        return answer


def session_path_for(ts_code: str, sessions_dir: Path, analysis_type: str = "") -> Path:
    ensure_dir(sessions_dir)
    suffix = f"_{analysis_type}" if analysis_type else ""
    return sessions_dir / f"{ts_code}{suffix}.json"
