"""求职猎手 Agent 专用确定性工具集（Domain Tools）。

严格划分「确定性规则边界」与「概率推理边界」：
1. prefilter_jd_rules：0 成本 Python 规则排雷 + 防间接提示词注入清洗（<untrusted_jd> 隔离）。
2. verify_and_save_package：用 Pydantic 强校验零造假边界（source_fact_id），通过后生成可读 Markdown 报告落盘。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from pydantic import ValidationError

from schemas import HardConstraintGateResult, JobHuntingPackage


ROOT = Path(__file__).resolve().parent
FACTS_PATH = ROOT / "data" / "candidate_facts.json"
OUTPUT_DIR = ROOT / "outputs"


def load_candidate_facts() -> dict[str, Any]:
    with FACTS_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def sanitize_untrusted_jd(raw_jd: str) -> str:
    """防间接提示词注入（Indirect Prompt Injection）清洗与标签物理隔离。"""
    # 剥离可能用于绕过边界的伪造闭合标签与可疑控制指令
    cleaned = re.sub(r"</?untrusted_jd>", "", raw_jd, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"(ignore\s+previous\s+instructions|忽略上述所有指令|忽略之前的指令)",
        "[REDACTED_INJECTION_ATTEMPT]",
        cleaned,
        flags=re.IGNORECASE,
    )
    return f"<untrusted_jd>\n{cleaned.strip()}\n</untrusted_jd>"


def prefilter_jd_rules(raw_jd: str) -> HardConstraintGateResult:
    """第 1 级门禁：0 Token 消耗的确定性保肾排雷器。"""
    profile = load_candidate_facts()
    blacklist: list[str] = profile["hard_constraints"]["toxic_keywords_blacklist"]

    triggered: list[str] = []
    lowered = raw_jd.casefold()
    for word in blacklist:
        if word.casefold() in lowered:
            triggered.append(word)

    # 额外正则模式检测隐形毒药（如“单休”、“驻场”、“纯算法预训练”）
    extra_patterns = [
        (r"每周工作\s*6\s*天", "每周工作6天（隐形大小周/单休）"),
        (r"客户现场驻场|外派驻场", "客户现场外派驻场"),
        (r"仅限\s*985\s*/?\s*211\s*硕士", "学历硬卡 985/211 硕士"),
    ]
    for pattern, label in extra_patterns:
        if re.search(pattern, raw_jd, flags=re.IGNORECASE):
            triggered.append(label)

    passed = len(triggered) == 0
    return HardConstraintGateResult(
        passed=passed,
        decision="GREEN_PROCEED" if passed else "RED_REJECTED",
        triggered_redlines=triggered,
        sanitized_jd_xml=sanitize_untrusted_jd(raw_jd),
    )


def _render_markdown_report(pkg: JobHuntingPackage) -> str:
    """将通过强类型校验的求职弹药包渲染为清爽易读的 Markdown 战报。"""
    lines = [
        f"# 🎯 求职猎手定制战报：{pkg.company_and_role}",
        "",
        f"- **最终建议**：`{pkg.verdict}`",
        f"- **保肾安全分**：**{pkg.kidney_safe_score} / 100**",
        f"- **技术匹配分**：**{pkg.overall_match_score} / 100**",
        f"- **核心诊断**：{pkg.verdict_reasoning}",
        "",
        "---",
        "",
        "## 一、 绕过 HR 直达技术负责人的 150 字打招呼话术（可直接复制）",
        "",
        f"> {pkg.direct_cto_pitch}",
        "",
        "---",
        "",
        "## 二、 零造假经历重译（已通过 `source_fact_id` 真实性校验）",
        "",
        "| 绑定真实履历 ID | 瞄准的 JD 要求 | 重译后的简历高光表述 |",
        "| :--- | :--- | :--- |",
    ]
    for b in pkg.reframed_bullets:
        lines.append(
            f"| `{b.source_fact_id}` | {b.jd_requirement_targeted} | {b.reframed_statement} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 三、 关键词覆盖与诚实缺口分析（Resume-Matcher 模式）",
        "",
        f"- ✅ **已直接覆盖**：{', '.join(pkg.keyword_analysis.matched_keywords) or '无'}",
        f"- 🔄 **前端/全栈同构平替**：{', '.join(pkg.keyword_analysis.reframed_keywords) or '无'}",
        f"- ⚠️ **诚实缺口（绝不硬塞造假，用工程优势回应）**：{', '.join(pkg.keyword_analysis.honest_gaps) or '无'}",
        "",
        "---",
        "",
        "## 四、 针对该 JD 的 3 道必考底层原理 30 秒速记卡",
        "",
    ])
    for idx, card in enumerate(pkg.interview_flashcards, 1):
        lines.extend([
            f"### 卡片 {idx}：{card.question}",
            f"- **物理本质**：{card.physical_essence}",
            f"- **前端直觉映射**：{card.frontend_analogy}",
            f"- **Agent 工程落地**：{card.engineering_action}",
            "",
        ])
    return "\n".join(lines)


def verify_and_save_package(package_payload: dict[str, Any]) -> dict[str, Any]:
    """Tool：执行 Pydantic 强类型校验（含零造假 fact_id 检查），通过后保存报告。"""
    try:
        validated = JobHuntingPackage.model_validate(package_payload)
    except ValidationError as exc:
        # 将详细校验失败原因返回给 Agent，触发其自我修正重试（第 5 章 Harness 自愈机制）
        # 注意：exc.errors() 中的 'ctx' 字典可能包含 ValueError 异常实例，必须转为字符串
        clean_errors = []
        for err in exc.errors(include_url=False):
            err_dict = dict(err)
            if "ctx" in err_dict and isinstance(err_dict["ctx"], dict):
                err_dict["ctx"] = {k: str(v) for k, v in err_dict["ctx"].items()}
            clean_errors.append(err_dict)

        return {
            "ok": False,
            "error_type": "ZeroFabricationOrSchemaValidationError",
            "details": clean_errors,
            "instruction": "请检查 source_fact_id 是否严格来自 candidate_facts.json，并补齐缺失字段后重新调用本工具。",
        }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fa5_-]+", "_", validated.company_and_role).strip("_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = OUTPUT_DIR / f"{timestamp}_{slug}.md"
    json_path = OUTPUT_DIR / f"{timestamp}_{slug}.json"

    md_path.write_text(_render_markdown_report(validated), encoding="utf-8")
    json_path.write_text(
        validated.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "saved_markdown": str(md_path),
        "saved_json": str(json_path),
        "verdict": validated.verdict,
        "kidney_safe_score": validated.kidney_safe_score,
        "overall_match_score": validated.overall_match_score,
    }


def get_openai_tools_schema() -> list[dict[str, Any]]:
    """由 Pydantic 模型自动导出标准 OpenAI Tool Schema（告别手写 tools.json）。"""
    return [
        {
            "type": "function",
            "function": {
                "name": "verify_and_save_package",
                "description": (
                    "验证并保存求职定制弹药包。系统会强制执行 Pydantic 零造假校验："
                    "每个 reframed_bullets 的 source_fact_id 必须存在于候选人真实履历库中。"
                    "若校验失败，请根据返回的 details 修正后重新调用。"
                ),
                "parameters": JobHuntingPackage.model_json_schema(),
            },
        }
    ]


def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """统一工具路由执行器。"""
    if name == "verify_and_save_package":
        return verify_and_save_package(arguments)
    return {"ok": False, "error": f"Unknown tool: {name}"}
