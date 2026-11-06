"""岗位自动打捞与智能初筛模块（Job Hunter Ingestion Engine）。

支持两大低风险、合规数据源通道：
1. V2EX 开放 API（jobs 节点 + remote 节点）：一键自动拉取最新的远程/全栈/AI 招聘帖子。
2. 本地收件箱（inbox/ 目录）：支持放入任何从 Boss直聘、微信群剪贴的文本文件。
3. 自动结合第 1 级保肾确定性门禁（prefilter_jd_rules）进行初步硬排雷。
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from domain_tools import prefilter_jd_rules

ROOT = Path(__file__).resolve().parent
INBOX_DIR = ROOT / "inbox"


def fetch_v2ex_node_topics(node_name: str) -> list[dict[str, Any]]:
    """调用 V2EX 开放 API 获取指定板块的最新帖子。"""
    url = f"https://www.v2ex.com/api/topics/show.json?node_name={node_name}"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) JobHunterAgent/1.0"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, list) else []
    except Exception as exc:
        print(f"⚠️ 拉取 V2EX [{node_name}] 节点失败: {exc}")
        return []


def scan_local_inbox() -> list[dict[str, Any]]:
    """扫描本地 inbox/ 目录下的所有用户剪贴的岗位文本文件。"""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    inbox_items: list[dict[str, Any]] = []
    for file_path in INBOX_DIR.glob("*.txt"):
        content = file_path.read_text(encoding="utf-8")
        inbox_items.append({
            "source": f"inbox/{file_path.name}",
            "title": file_path.stem,
            "content": content,
            "url": "local_file",
            "created_time": datetime.fromtimestamp(file_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    for file_path in INBOX_DIR.glob("*.md"):
        content = file_path.read_text(encoding="utf-8")
        inbox_items.append({
            "source": f"inbox/{file_path.name}",
            "title": file_path.stem,
            "content": content,
            "url": "local_file",
            "created_time": datetime.fromtimestamp(file_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return inbox_items


def score_profile_keyword_overlap(text: str) -> int:
    """基于林雪人真实履历的技术画像打出关键词相关度基础分（0-100）。"""
    lowered = text.casefold()
    keywords = [
        ("agent", 20),
        ("ai", 15),
        ("远程", 25),
        ("remote", 25),
        ("成都", 20),
        ("前端", 15),
        ("frontend", 15),
        ("全栈", 15),
        ("fullstack", 15),
        ("next.js", 15),
        ("fastapi", 15),
        ("python", 10),
        ("typescript", 10),
        ("react", 10),
        ("vue", 10),
        ("rag", 10),
        ("hitl", 15),
    ]
    score = 0
    for kw, weight in keywords:
        if kw in lowered:
            score += weight
    return min(score, 100)


def harvest_and_filter_jobs(*, fetch_online: bool = True) -> list[dict[str, Any]]:
    """汇聚所有数据源，经过保肾排雷与画像相关度初筛，返回高潜岗位列表。"""
    raw_candidates: list[dict[str, Any]] = []

    # 1. 本地收件箱
    raw_candidates.extend(scan_local_inbox())

    # 2. V2EX 远程与招聘节点
    if fetch_online:
        for node in ["remote", "jobs"]:
            topics = fetch_v2ex_node_topics(node)
            for t in topics:
                title = t.get("title", "")
                content = t.get("content", "") or ""
                url = t.get("url", f"https://www.v2ex.com/t/{t.get('id', '')}")
                raw_candidates.append({
                    "source": f"V2EX-{node}",
                    "title": title,
                    "content": f"【标题】: {title}\n【来源链接】: {url}\n\n【正文】:\n{content}",
                    "url": url,
                    "created_time": datetime.fromtimestamp(t.get("created", 0)).strftime("%Y-%m-%d %H:%M") if t.get("created") else "N/A",
                })

    processed_jobs: list[dict[str, Any]] = []
    for item in raw_candidates:
        full_text = f"{item['title']}\n{item['content']}"
        # 第 1 级门禁：保肾确定性排雷（拒 996 / 驻场外包 / 大小周）
        gate_res = prefilter_jd_rules(full_text)
        relevance = score_profile_keyword_overlap(full_text)

        processed_jobs.append({
            "source": item["source"],
            "title": item["title"],
            "url": item["url"],
            "gate_passed": gate_res.passed,
            "decision": gate_res.decision,
            "triggered_redlines": gate_res.triggered_redlines,
            "relevance_score": relevance,
            "raw_text": full_text,
            "sanitized_xml": gate_res.sanitized_jd_xml,
        })

    # 排序：优先排雷通过（绿灯），且技术相关度最高
    processed_jobs.sort(key=lambda x: (1 if x["gate_passed"] else 0, x["relevance_score"]), reverse=True)
    return processed_jobs


if __name__ == "__main__":
    print("🚀 启动岗位雷达扫描与保肾初筛...")
    jobs = harvest_and_filter_jobs()
    print(f"📊 共扫描到 {len(jobs)} 个岗位。")
    green_jobs = [j for j in jobs if j["gate_passed"] and j["relevance_score"] >= 30]
    print(f"✅ 绿灯推荐候选岗位: {len(green_jobs)} 个\n")

    for i, j in enumerate(green_jobs[:5], 1):
        print(f"[{i}] [{j['source']}] 匹配度: {j['relevance_score']}分 | {j['title']}")
        print(f"    链接: {j['url']}")
