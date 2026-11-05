# job-hunter-agent

> 专为资深工程师量身定制的「保肾级求职猎手 Agent」（V0.1 黄金底座）。
> 基于《AI Agent 实践》第 5 章黄金模板（`reference_agent`）基因变异重构，吸收 GitHub 顶流求职工具最佳实践。

## 核心特性
- **两级排雷漏斗（Two-Stage Funnel）**：第 1 级 0 成本 Python 规则秒杀外包/996/驻场；第 2 级大模型深度匹配。
- **零造假事实锚定（Zero-Fabrication）**：Pydantic 运行时强类型校验，强制所有定制简历亮点必须绑定本地真实履历 `source_fact_id`。
- **KV Cache 稳定设计**：静态置顶 System Prompt 与事实库，尾部 `<system_hint>` 临时注入动态进度，不污染缓存前缀。
- **思维链保留协议**：原生兼容 DeepSeek / OpenAI o3 / Kimi-K2 跨轮 `reasoning_content` 回传。
- **防间接提示词注入**：外部不可信 JD 严格包裹于 `<untrusted_jd>` 标签并剥离控制指令。

## 运行与测试
```bash
# 运行离线演示
python3 main.py --dry-run

# 执行五大边界测试
pytest tests/test_boundaries.py -v
```
