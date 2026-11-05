"""2026 生产级 Agent 黄金底座（升级自《AI Agent 实践》第 5 章 reference_agent）。

核心架构特性（面试投屏核心看点）：
1. 黄金模板变异模式：底层 ReAct 循环锁死，仅通过 system_prompt.md 与 domain_tools.py 注入求职领域逻辑。
2. KV Cache 前缀绝对稳定：静态 System Prompt + 真实履历库锁定在第 0 位，动态提示通过尾部 <system_hint> 临时注入，不污染历史前缀。
3. 思考链（Reasoning Content）原样回传协议：兼容 DeepSeek-R1/V4、Kimi-K2、OpenAI o3/GPT-5 等推理模型，避免多轮工具调用时丢失中间推理状态或触发 API 400 错误（对应第 2 章 §522）。
4. 两级漏斗门禁（Two-Stage Funnel）：先跑 0 成本 Python 确定性排雷（prefilter_jd_rules），红灯毒药岗直接拦截，绿灯岗才唤醒大模型。
5. 工具异常自愈闭环：Pydantic 零造假校验失败时不中断进程，而是封装为 role="tool" 消息回传模型触发自我修正。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from domain_tools import (
    execute_tool,
    get_openai_tools_schema,
    load_candidate_facts,
    prefilter_jd_rules,
)


ROOT = Path(__file__).resolve().parent


class JobHunterAgent:
    """保肾级求职猎手 Agent（V0.1 黄金底座）。"""

    def __init__(self, *, model: str | None = None, client: Any | None = None):
        self.model = (
            model
            or os.getenv("OPENAI_MODEL")
            or os.getenv("OPENROUTER_MODEL")
            or "deepseek-chat"
        )
        self.client = client or self._init_default_client()
        self.system_prompt = self._build_static_system_prompt()
        self.tools = get_openai_tools_schema()

    def _init_default_client(self) -> Any:
        """按环境变量初始化 OpenAI 兼容客户端（支持 OpenAI / OpenRouter / DeepSeek / Kimi / Ollama）。"""
        from openai import OpenAI

        use_router = bool(os.getenv("OPENROUTER_API_KEY"))
        api_key = (
            os.getenv("OPENROUTER_API_KEY")
            if use_router
            else (os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY"))
        )
        base_url = (
            "https://openrouter.ai/api/v1"
            if use_router
            else (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1")
        )
        if not api_key:
            raise RuntimeError(
                "未检测到 API Key。请设置 OPENAI_API_KEY / OPENROUTER_API_KEY，或使用 --dry-run 模式测试确定性门禁。"
            )
        return OpenAI(api_key=api_key, base_url=base_url)

    @staticmethod
    def _build_static_system_prompt() -> str:
        """构建静态置顶 System Prompt，确保跨轮次与跨任务 100% 命中前缀 KV Cache。"""
        template = (ROOT / "system_prompt.md").read_text(encoding="utf-8")
        facts_json = json.dumps(load_candidate_facts(), ensure_ascii=False, indent=2)
        return template.replace("{{CANDIDATE_FACTS_JSON}}", facts_json)

    @staticmethod
    def _assistant_message(message: Any) -> dict[str, Any]:
        """组装标准 Assistant 消息，原样保留 reasoning_content 思考链（2026 生产级规范）。"""
        result: dict[str, Any] = {
            "role": "assistant",
            "content": getattr(message, "content", None) or "",
        }
        # 关键补丁：保留推理模型的思维链字段，防止多轮 Tool Call 报 400 错误或断片
        reasoning = getattr(message, "reasoning_content", None)
        if reasoning:
            result["reasoning_content"] = reasoning

        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            result["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in tool_calls
            ]
        return result

    @staticmethod
    def _build_tail_system_hint(iteration: int, max_iterations: int) -> str:
        """生成尾部动态状态提示（<system_hint>），避免修改头部 System Prompt 破坏 KV Cache。"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        return (
            f"<system_hint>\n"
            f"当前迭代轮次: {iteration}/{max_iterations} | 本地时间: {now_str}\n"
            f"提醒: 请确保所有 reframed_bullets 的 source_fact_id 严格取自候选人真实履历库（FACT-AI-01..03, FACT-FE-01..03），"
            f"并调用 verify_and_save_package 完成落盘验收。\n"
            f"</system_hint>"
        )

    def evaluate_jd(
        self,
        raw_jd: str,
        *,
        max_iterations: int = 6,
    ) -> dict[str, Any]:
        """完整两级漏斗执行入口：第 1 级确定性规则排雷 -> 第 2 级 Agent 循环定制。"""
        # ========== 第 1 级：0 成本确定性门禁 ==========
        gate = prefilter_jd_rules(raw_jd)
        if not gate.passed:
            return {
                "ok": True,
                "stage": "STAGE_1_DETERMINISTIC_GATE_BLOCKED",
                "decision": gate.decision,
                "triggered_redlines": gate.triggered_redlines,
                "answer": (
                    f"🛑 【保肾门禁 0 成本直接拦截】命中硬性排雷红线：{', '.join(gate.triggered_redlines)}。"
                    f"已为您节省大模型 Token 与宝贵精力，建议直接略过该岗位！"
                ),
                "usage": {
                    "prompt_tokens": 0,
                    "cached_prompt_tokens": 0,
                    "completion_tokens": 0,
                    "requests": 0,
                },
            }

        # ========== 第 2 级：LLM 深度评估与定制弹药生成 ==========
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": (
                    "请评估以下外部招聘 JD（已做防注入隔离），并调用 `verify_and_save_package` "
                    "生成求职定制弹药包与 3 道必考底层原理速记卡：\n\n"
                    f"{gate.sanitized_jd_xml}"
                ),
            },
        ]
        trace: list[dict[str, Any]] = []
        usage_totals = {
            "prompt_tokens": 0,
            "cached_prompt_tokens": 0,
            "completion_tokens": 0,
            "requests": 0,
        }
        saved_artifact: dict[str, Any] | None = None

        for iteration in range(1, max_iterations + 1):
            # 拷贝消息列表并在尾部临时追加 <system_hint>，不污染原历史前缀
            request_messages = [
                *messages,
                {"role": "user", "content": self._build_tail_system_hint(iteration, max_iterations)},
            ]
            kwargs: dict[str, Any] = dict(
                model=self.model,
                messages=request_messages,
                tools=self.tools,
                tool_choice="auto",
                temperature=1 if any(k in self.model.casefold() for k in ("kimi-", "gpt-5")) else 0,
            )
            response = self.client.chat.completions.create(**kwargs)
            message = response.choices[0].message
            messages.append(self._assistant_message(message))

            # 统计 Token 与 KV Cache 命中率
            usage = getattr(response, "usage", None)
            prompt_details = getattr(usage, "prompt_tokens_details", None)
            usage_totals["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
            usage_totals["cached_prompt_tokens"] += (
                getattr(prompt_details, "cached_tokens", 0)
                or getattr(usage, "prompt_cache_hit_tokens", 0)
                or 0
            )
            usage_totals["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
            usage_totals["requests"] += 1

            trace.append({
                "iteration": iteration,
                "has_reasoning": bool(getattr(message, "reasoning_content", None)),
                "tool_calls": len(message.tool_calls or []),
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "cached_tokens": getattr(prompt_details, "cached_tokens", None),
            })

            if not message.tool_calls:
                return {
                    "ok": True,
                    "stage": "STAGE_2_AGENT_COMPLETED",
                    "answer": message.content or "",
                    "saved_artifact": saved_artifact,
                    "iterations": iteration,
                    "trace": trace,
                    "usage": usage_totals,
                }

            for call in message.tool_calls:
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                    result = execute_tool(call.function.name, arguments)
                    if result.get("ok") and call.function.name == "verify_and_save_package":
                        saved_artifact = result
                except Exception as exc:
                    result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

        return {
            "ok": False,
            "stage": "MAX_ITERATIONS_EXCEEDED",
            "answer": "",
            "saved_artifact": saved_artifact,
            "iterations": max_iterations,
            "trace": trace,
            "usage": usage_totals,
            "error": "maximum iterations reached",
        }
