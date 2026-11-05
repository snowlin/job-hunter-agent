"""强类型边界契约（Pydantic V2 Schemas）。

融合三大开源项目与《AI Agent 实践》第 5/7 章核心设计：
1. sliday/resume-job-matcher：硬约束前置门禁 + 强制绑定真实履历 fact_id 证据锚点（Zero-Fabrication）。
2. srbhr/Resume-Matcher：JD 核心关键词命中与诚实缺口热力对比（禁止硬塞虚假词）。
3. 针对该岗位自动生成「直达技术负责人打招呼话术」与「3 道必考底层原理 30 秒速记卡」。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, field_validator


DATA_FILE = Path(__file__).resolve().parent / "data" / "candidate_facts.json"


def load_valid_fact_ids() -> set[str]:
    """从本地真实履历库读取所有合法的 fact_id 集合（确定性真源）。"""
    with DATA_FILE.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return {item["fact_id"] for item in data.get("verified_facts", [])}


class HardConstraintGateResult(BaseModel):
    """第 1 级：0 成本确定性门禁结果（无需消耗 LLM Token）。"""

    passed: bool = Field(description="是否通过保肾与硬性红线门禁")
    decision: Literal["GREEN_PROCEED", "RED_REJECTED"]
    triggered_redlines: list[str] = Field(
        default_factory=list,
        description="命中的毒药黑名单词或硬伤（如：996、大小周、驻场外包）",
    )
    sanitized_jd_xml: str = Field(
        description="经过防提示词注入清洗并包裹在 <untrusted_jd> 标签内的安全文本"
    )


class ReframedExperienceBullet(BaseModel):
    """零造假经历重译项：强制绑定本地真实履历 ID。"""

    source_fact_id: str = Field(
        description="必须严格引用 candidate_facts.json 中已存在的 fact_id（如 FACT-AI-01, FACT-FE-01）"
    )
    jd_requirement_targeted: str = Field(
        description="该条经历所对应的 JD 具体要求"
    )
    reframed_statement: str = Field(
        description="基于真实事实重译后的高匹配度表述（如将前端复杂状态机重译为 Agent Harness 状态流转与容错经验，严禁捏造未做过的技术栈）"
    )

    @field_validator("source_fact_id")
    @classmethod
    def validate_fact_id_exists(cls, value: str) -> str:
        valid_ids = load_valid_fact_ids()
        if value not in valid_ids:
            raise ValueError(
                f"零造假边界拦截：非法或捏造的 source_fact_id '{value}'！"
                f"仅允许引用真实履历 ID：{sorted(valid_ids)}"
            )
        return value


class KeywordGapAnalysis(BaseModel):
    """参考 srbhr/Resume-Matcher 的关键词对齐与诚实缺口分析。"""

    matched_keywords: list[str] = Field(
        description="候选人真实履历已覆盖的 JD 关键词"
    )
    reframed_keywords: list[str] = Field(
        description="可通过 13 年前端/全栈经验直接平替迁移的关键词（如：流式渲染 -> SSE/Agent Streaming）"
    )
    honest_gaps: list[str] = Field(
        description="候选人确实不具备、绝不硬塞造假的缺口词（附带面试时如何用工程优势化解的策略）"
    )


class CorePrincipleFlashcard(BaseModel):
    """专治面试怕被问底层原理：针对当前 JD 定制的 30 秒速记卡。"""

    question: str = Field(description="面试官极可能根据该 JD 追问的底层原理问题")
    physical_essence: str = Field(description="1 句话点破物理/数学本质（不背复杂公式）")
    frontend_analogy: str = Field(description="映射到候选人熟悉的 13 年前端架构直觉")
    engineering_action: str = Field(description="在 Agent 代码中如何具体落地规避坑点")


class JobHuntingPackage(BaseModel):
    """第 2 级：求职猎手 Agent 最终交付的定制弹药包（强类型结构化输出）。"""

    company_and_role: str = Field(description="公司与岗位名称")
    kidney_safe_score: int = Field(
        ge=0, le=100, description="保肾与 WLB 安全指数（0-100，低于 60 建议放弃）"
    )
    overall_match_score: int = Field(
        ge=0, le=100, description="技术与经验综合匹配度（0-100）"
    )
    verdict: Literal["STRONG_APPLY", "CAUTIOUS_APPLY", "DO_NOT_APPLY"] = Field(
        description="最终投递建议"
    )
    verdict_reasoning: str = Field(description="一针见血的适配与排雷结论")
    direct_cto_pitch: str = Field(
        description="绕过 HR 机筛、直击业务技术负责人痛点的 150 字以内黄金打招呼话术（禁止 AI 套话，直接亮出美的金融状态机底座 + AI 全栈作品）"
    )
    reframed_bullets: list[ReframedExperienceBullet] = Field(
        min_length=2,
        description="至少 2 条基于真实 fact_id 重译的简历定制亮点",
    )
    keyword_analysis: KeywordGapAnalysis
    interview_flashcards: list[CorePrincipleFlashcard] = Field(
        min_length=3,
        max_length=3,
        description="针对该 JD 技术栈定制的 3 张底层原理 30 秒速记卡",
    )
