"""Prompt construction utilities for the Excel to Markdown Wiki LLM pipeline.

Provides the system prompt, user-prompt builder, and Ollama API payload
assembler used when generating Markdown wiki pages from FaultCase data.
"""

from __future__ import annotations

import json

from models import FaultCase

# ---------------------------------------------------------------------------
# System prompt — defines the LLM's role and output rules
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "你是一名运维文档专家。你的任务是将提供的故障案例数据转换为结构化的 Markdown 文档。\n"
    "\n"
    "请严格遵守以下规则：\n"
    "\n"
    "1. 仅输出 Markdown 内容，不要输出任何对话性开头、结尾或解释说明。\n"
    "2. 禁止生成任何图表、流程图或 Mermaid 语法，只使用纯文本表述。\n"
    "3. 始终保持文档层级结构：故障现象 → 定界手段 → 恢复方案。\n"
    "4. 涉及危险操作时，必须使用 `> [!WARNING]` 引用语法进行醒目标注。\n"
    "5. 所有命令必须放在代码块中，并标注语言类型（如 ```bash、```sql）。\n"
    "6. 保留数据中的缺失标记（如 `[缺失关联数据：ID xxxx]`），不得删除或修改。\n"
    "7. 当被要求生成参考建议时，在文档末尾添加「## 参考建议（LLM 生成）」章节，"
    "用 `> [!NOTE]` 引用块明确标注为 LLM 参考建议，提示用户根据实际情况调整。\n"
    "8. 当数据中包含「来自相似故障的定界手段和恢复方案」时，请将它们整合到"
    "「## 定界手段」和「## 恢复方案」章节中，并在每个整合的条目标题后标注来源，"
    "格式为「（来自相似故障 {source_fault_id}-{source_fault_name}）」。\n"
)

# ---------------------------------------------------------------------------
# User prompt builder
# ---------------------------------------------------------------------------


def build_prompt(fault_case: FaultCase, generate_suggestions: bool = False) -> str:
    """Build the user prompt for the LLM from a FaultCase instance.

    The prompt serialises the fault case to pretty-printed JSON and instructs
    the model to convert it into a Markdown document following a specific
    heading hierarchy.

    When *generate_suggestions* is True and the fault case has missing data,
    additional instructions are appended asking the LLM to generate reference
    diagnostic methods and/or recovery plans.

    When the fault case has merged data from similar phenomena, the prompt
    includes instructions for integrating those into the output document.

    Args:
        fault_case: A fully resolved FaultCase object.
        generate_suggestions: Whether to ask the LLM for suggestions on missing data.

    Returns:
        The complete user-prompt string ready for the LLM.
    """
    data = fault_case.to_dict()
    data_json = json.dumps(data, ensure_ascii=False, indent=2)

    prompt = (
        "请将以下故障案例 JSON 数据转换为结构化的 Markdown 文档。\n"
        "\n"
        "文档结构要求如下：\n"
        "\n"
        f"- # PL-{{fault_id}}-{{phenomenon_name}}（使用 JSON 中的 fault_id 和 phenomenon_name 替换）\n"
        "- ## 故障描述\n"
        "- ## 定界手段\n"
        "  - ### 定界手段{diagnostic_id}-{定界方法名称}（含定界工具和定界结果，"
        "使用 JSON 中的 diagnostic_id 和 name 替换）\n"
        "    - 在每个定界手段章节开头列出该手段关联的恢复方案编号，"
        "格式为「**关联恢复方案**：recovery_id1、recovery_id2」，"
        "使用 JSON 中该 diagnostic 下 recoveries 列表里每个 recovery 的 recovery_id。"
        "若无关联恢复方案则写「**关联恢复方案**：无」。\n"
        "- ## 恢复方案\n"
        "  - ### 恢复方案{recovery_id}-{恢复方案名称}（含恢复工具，"
        "使用 JSON 中的 recovery_id 和 name 替换）\n"
        "\n"
        "故障案例数据：\n"
        f"```json\n{data_json}\n```"
    )

    if fault_case.merged_diagnostics or fault_case.merged_recoveries:
        prompt += (
            "\n\n"
            "**重要**：上述 JSON 数据中包含 `merged_from_similar` 字段，"
            "这些是来自相似故障现象的定界手段和恢复方案（已通过 LLM 相似性分析确认）。"
            "请将它们整合到本文档的「## 定界手段」和「## 恢复方案」章节中，"
            "与原有的定界手段和恢复方案并列展示。"
            "在每个来自相似故障的条目标题后标注来源，"
            "格式为「（来自相似故障 {source_fault_id}-{source_fault_name}）」。"
        )

    if generate_suggestions and fault_case.needs_llm_suggestions:
        missing_items: list[str] = []
        if len(fault_case.diagnostics) == 0:
            missing_items.append("- 该故障现象无对应的定界手段")
        if len(fault_case.recoveries) == 0:
            missing_items.append("- 该故障现象无对应的恢复方案")
        for mid in fault_case.missing_ids:
            missing_items.append(f"- {mid}")

        prompt += (
            "\n\n"
            "注意：该故障案例存在缺失数据：\n"
            + "\n".join(missing_items)
            + "\n\n"
            "请根据故障现象名称和描述，在文档末尾添加「## 参考建议（LLM 生成）」章节，"
            "基于你的运维经验提供参考的定界手段和/或恢复方案建议。"
            "建议内容必须用以下格式标注：\n"
            "> [!NOTE]\n"
            "> 以下为 LLM 参考建议，请根据实际情况调整。\n"
        )

    return prompt


# ---------------------------------------------------------------------------
# Ollama API payload builder
# ---------------------------------------------------------------------------


def build_llm_payload(prompt: str, config: dict, system_prompt: str | None = None) -> dict:
    """Assemble the full request payload for the Ollama /api/generate endpoint.

    Args:
        prompt: The user prompt string (typically from build_prompt).
        config: Application config dict containing an ``llm`` section with at
            least ``model`` and ``temperature`` keys.
        system_prompt: Optional system prompt override. When None, uses the
            default SYSTEM_PROMPT.

    Returns:
        A dict ready to be JSON-encoded and sent to Ollama.
    """
    llm = config["llm"]
    payload = {
        "model": llm["model"],
        "system": system_prompt or SYSTEM_PROMPT,
        "prompt": prompt,
        "stream": False,
        "think": llm.get("enable_thinking", False),
        "options": {
            "temperature": llm["temperature"],
        },
    }
    return payload


# ---------------------------------------------------------------------------
# OpenAI Chat Completions payload builder
# ---------------------------------------------------------------------------


def build_openai_payload(prompt: str, config: dict, system_prompt: str | None = None) -> dict:
    """Assemble the request payload for the OpenAI Chat Completions API.

    Args:
        prompt: The user prompt string (typically from build_prompt).
        config: Application config dict containing an ``llm`` section.
        system_prompt: Optional system prompt override. When None, uses the
            default SYSTEM_PROMPT.

    Returns:
        A dict with ``messages`` and keyword arguments for
        ``client.chat.completions.create()``.
    """
    llm = config["llm"]
    return {
        "model": llm["model"],
        "messages": [
            {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": llm["temperature"],
        "stream": False,
    }
