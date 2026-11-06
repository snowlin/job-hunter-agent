"""岗位定时巡检器与时效过滤雷达（Scheduled Job Monitor with Time Horizon & Deduplication）。

核心特性：
1. 严格时效门禁（Time Horizon）：默认只抓取最近 N 天（如 3 天 / 7 天）内发布的最新岗位，剔除陈旧过期招聘。
2. 本地已处理历史去重（Deduplication）：基于 SQLite / JSON 记录已巡检过的帖子 ID 与 URL，绝不重复提醒打扰。
3. 守护进程 / 一次性执行双模式：
   - 模式 A（常驻守护模式）：使用定时循环按固定间隔（如每 4 小时 / 每天早上 9 点）自动巡检。
   - 模式 B（macOS launchd / 外部 cron 触发）：单次运行，发现新岗位时写入 outputs/daily_digest/ 并输出提醒。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from job_crawler import harvest_and_filter_jobs

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "job_history.db"
DIGEST_DIR = ROOT / "outputs" / "daily_digest"


def init_history_db() -> None:
    """初始化用于存储已处理岗位 ID 的轻量 SQLite 数据库。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS seen_jobs (
                id TEXT PRIMARY KEY,
                source TEXT,
                title TEXT,
                url TEXT,
                relevance_score INTEGER,
                gate_passed INTEGER,
                first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def get_seen_job_ids() -> set[str]:
    """读取已记录的岗位唯一标识集合。"""
    init_history_db()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT id FROM seen_jobs")
        return {row[0] for row in cursor.fetchall()}


def mark_jobs_as_seen(jobs: list[dict[str, Any]]) -> None:
    """将新扫描到的岗位批量入库记录。"""
    init_history_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO seen_jobs (id, source, title, url, relevance_score, gate_passed)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    j.get("url", j["title"]),
                    j.get("source", "unknown"),
                    j["title"],
                    j.get("url", ""),
                    j.get("relevance_score", 0),
                    1 if j.get("gate_passed") else 0,
                )
                for j in jobs
            ],
        )
        conn.commit()


def run_scheduled_scan(*, max_days: int = 3, min_score: int = 40) -> list[dict[str, Any]]:
    """执行一次定点巡检：仅保留最近 max_days 天且从未推送过的新增高分岗位。"""
    init_history_db()
    seen_ids = get_seen_job_ids()
    now = datetime.now()
    cutoff_time = now - timedelta(days=max_days)

    print(f"⏰ [{now.strftime('%Y-%m-%d %H:%M:%S')}] 启动定时巡检雷达...")
    print(f"🎯 时效窗口：仅保留 {max_days} 天内最新发布（{cutoff_time.strftime('%Y-%m-%d')} 之后）")

    all_jobs = harvest_and_filter_jobs(fetch_online=True)

    fresh_qualified_jobs: list[dict[str, Any]] = []
    for j in all_jobs:
        job_id = j.get("url", j["title"])
        # 1. 过滤已见岗位
        if job_id in seen_ids:
            continue

        # 2. 过滤未通过保肾硬门禁的毒药岗
        if not j.get("gate_passed", False):
            continue

        # 3. 过滤匹配分低于阈值的无关岗位
        if j.get("relevance_score", 0) < min_score:
            continue

        # 4. 检查发布时间时效
        created_str = j.get("created_time")
        if created_str and created_str != "N/A":
            try:
                created_dt = datetime.strptime(created_str, "%Y-%m-%d %H:%M")
                if created_dt < cutoff_time:
                    continue
            except Exception:
                pass

        fresh_qualified_jobs.append(j)

    if not fresh_qualified_jobs:
        print("☕ 本轮巡检未发现新增的高潜岗位，不打扰用户。")
        return []

    print(f"🎉 发现 {len(fresh_qualified_jobs)} 个符合条件的新增最新岗位！")

    # 标记已记录
    mark_jobs_as_seen(fresh_qualified_jobs)

    # 渲染 Markdown 简报落盘
    DIGEST_DIR.mkdir(parents=True, exist_ok=True)
    digest_filename = f"digest_{now.strftime('%Y%m%d_%H%M%S')}.md"
    digest_path = DIGEST_DIR / digest_filename

    lines = [
        f"# 📡 今日最新高潜岗位巡检简报 ({now.strftime('%Y-%m-%d %H:%M')})",
        "",
        f"> 本轮巡检共发现 **{len(fresh_qualified_jobs)}** 个最近 {max_days} 天内发布、符合保肾红线且技术高度契合的远程/AI 岗位：",
        "",
    ]
    for idx, job in enumerate(fresh_qualified_jobs, 1):
        lines.extend([
            f"### {idx}. [{job['relevance_score']}分] {job['title']}",
            f"- **来源**: `{job['source']}` | **发布时间**: `{job.get('created_time', '近期')}`",
            f"- **链接**: [{job['url']}]({job['url']})",
            f"- **岗位摘要速览**:",
            "```text",
            job["raw_text"][:350].strip() + "\n...",
            "```",
            "",
            "---",
            "",
        ])

    digest_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"📄 已生成最新岗位简报: {digest_path}")
    return fresh_qualified_jobs


def start_daemon_loop(interval_hours: int = 4, max_days: int = 3) -> None:
    """常驻后台轮询模式（每隔 interval_hours 小时巡检一次）。"""
    print(f"🔄 启动常驻定时巡检守护进程：每隔 {interval_hours} 小时巡检一次...")
    while True:
        try:
            run_scheduled_scan(max_days=max_days)
        except Exception as exc:
            print(f"⚠️ 巡检执行异常: {exc}")
        
        sleep_seconds = interval_hours * 3600
        print(f"💤 进入休眠，下一次巡检将在 {interval_hours} 小时后执行...\n")
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="求职雷达定时巡检与时效过滤工具")
    parser.add_argument("--days", type=int, default=3, help="只看最近几天内发布的岗位（默认: 3天）")
    parser.add_argument("--daemon", action="store_true", help="以常驻守护模式运行（按指定间隔循环轮询）")
    parser.add_argument("--interval", type=int, default=4, help="常驻模式下的巡检间隔小时数（默认: 4小时）")
    args = parser.parse_args()

    if args.daemon:
        start_daemon_loop(interval_hours=args.interval, max_days=args.days)
    else:
        run_scheduled_scan(max_days=args.days)
