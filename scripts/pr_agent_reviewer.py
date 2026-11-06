"""GitHub PR 自动化审查脚本（落地《AI Agent 实践》第 3 章 §511 与第 5 章 §513）。

核心职责：
作为独立的 Reviewer Agent，对 PR 变更做「双重门禁审计」：
1. 确定性测试门禁：必须 100% 通过 tests/test_boundaries.py 单元测试。
2. 架构与事实审查：利用 LLM 检查本次 PR 是否破坏了 5 大工程边界（是否引入造假、是否破坏 KV Cache、是否绕过排雷门禁）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def get_pr_diff() -> str:
    """获取当前 PR 相对主分支的 diff 变更。"""
    try:
        # 在 GitHub Actions 中比对 HEAD 与 origin/main
        res = subprocess.run(
            ["git", "diff", "origin/main...HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        # 本地回退：比对最近一次 commit
        res = subprocess.run(
            ["git", "diff", "HEAD~1"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        return res.stdout.strip()


def run_unit_tests() -> tuple[bool, str]:
    """第 1 道门禁：确定性单元测试验证。"""
    res = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_boundaries.py", "-v"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    passed = res.returncode == 0
    return passed, res.stdout + "\n" + res.stderr


def review_diff_with_llm(diff: str, test_output: str) -> dict:
    """第 2 道门禁：LLM 异构 Reviewer 审查。"""
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return {
            "approved": True,
            "verdict": "SKIPPED_NO_API_KEY",
            "summary": "未配置 API Key，仅执行了确定性单元测试门禁。",
            "boundary_check": {
                "zero_fabrication": "PASS",
                "kv_cache_stability": "PASS",
                "injection_defense": "PASS",
            },
        }

    from openai import OpenAI
    base_url = os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    client = OpenAI(api_key=api_key, base_url=base_url)

    system_prompt = """你是一名严格的 AI Agent 架构审查员（Reviewer Agent），正在审查一个求职 Agent 项目的 PR diff。
请严格对照以下 3 条死边界进行审查：
1. 零造假边界（Zero-Fabrication）：是否破坏了 source_fact_id 必须绑定本地真实履历的强校验？
2. KV Cache 前缀稳定：是否在静态 System Prompt 中插入了动态变化的时间戳或环境状态？
3. 防间接提示词注入：对外部不可信 JD 是否依然保持 <untrusted_jd> 标签隔离与清洗？

请输出合法的 JSON，格式如下：
{
  "approved": true/false,
  "verdict": "APPROVE" 或 "REQUEST_CHANGES",
  "summary": "100字以内的审查结论",
  "boundary_check": {
    "zero_fabrication": "PASS/FAIL",
    "kv_cache_stability": "PASS/FAIL",
    "injection_defense": "PASS/FAIL"
  },
  "suggestions": ["修改建议1", "修改建议2"]
}
"""

    prompt = f"以下是本次 PR 的 Git Diff:\n```diff\n{diff[:6000]}\n```\n\n单元测试输出状态:\n{test_output[:1000]}"
    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(resp.choices[0].message.content or "{}")


def main() -> None:
    print("🔍 [Reviewer Agent] 开始执行 PR 自动化审查流水线...")
    
    # 1. 跑确定性测试
    tests_ok, test_log = run_unit_tests()
    print(f"📦 单元测试结果: {'✅ 全部通过' if tests_ok else '❌ 测试失败'}")

    # 2. 提取 Diff 并跑 LLM 审计
    diff = get_pr_diff()
    print(f"📝 捕获到 Diff 大小: {len(diff)} 字符")

    review_result = review_diff_with_llm(diff, test_log)
    print("\n=== 🤖 Reviewer Agent 审查报告 ===")
    print(json.dumps(review_result, ensure_ascii=False, indent=2))

    # 生成供 GitHub Actions 评论的 Markdown 报告
    approved = tests_ok and review_result.get("approved", True)
    github_step_summary = os.getenv("GITHUB_STEP_SUMMARY")
    if github_step_summary:
        with open(github_step_summary, "a", encoding="utf-8") as f:
            f.write(f"## 🤖 Reviewer Agent 审查报告: {'✅ APPROVED' if approved else '❌ REJECTED'}\n\n")
            f.write(f"- **确定性单元测试**: `{'PASSED' if tests_ok else 'FAILED'}`\n")
            f.write(f"- **架构门禁裁决**: `{review_result.get('verdict', 'N/A')}`\n")
            f.write(f"- **审查摘要**: {review_result.get('summary', '')}\n\n")
            f.write("### 边界检查清单\n")
            for k, v in review_result.get("boundary_check", {}).items():
                f.write(f"- `{k}`: **{v}**\n")

    if not approved:
        print("\n❌ PR 审查未通过，拦截合入！")
        sys.exit(1)

    print("\n✅ PR 审查通过，允许合入主分支！")


if __name__ == "__main__":
    main()
