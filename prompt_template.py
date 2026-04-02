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
)

# ---------------------------------------------------------------------------
# User prompt builder
# ---------------------------------------------------------------------------


def build_prompt(fault_case: FaultCase) -> str:
    """Build the user prompt for the LLM from a FaultCase instance.

    The prompt serialises the fault case to pretty-printed JSON and instructs
    the model to convert it into a Markdown document following a specific
    heading hierarchy.

    Args:
        fault_case: A fully resolved FaultCase object.

    Returns:
        The complete user-prompt string ready for the LLM.
    """
    data = fault_case.to_dict()
    data_json = json.dumps(data, ensure_ascii=False, indent=2)

    return (
        "请将以下故障案例 JSON 数据转换为结构化的 Markdown 文档。\n"
        "\n"
        "文档结构要求如下：\n"
        "\n"
        "- # 故障现象名称（故障ID）\n"
        "- ## 故障描述\n"
        "- ## 定界手段\n"
        "  - ### 各定界方法详情\n"
        "- ## 恢复方案\n"
        "  - ### 各恢复方案详情\n"
        "\n"
        "故障案例数据：\n"
        f"```json\n{data_json}\n```"
    )

# ---------------------------------------------------------------------------
# Ollama API payload builder
# ---------------------------------------------------------------------------


def build_llm_payload(prompt: str, config: dict) -> dict:
    """Assemble the full request payload for the Ollama /api/generate endpoint.

    Args:
        prompt: The user prompt string (typically from build_prompt).
        config: Application config dict containing an ``llm`` section with at
            least ``model`` and ``temperature`` keys.

    Returns:
        A dict ready to be JSON-encoded and sent to Ollama.
    """
    llm = config["llm"]
    return {
        "model": llm["model"],
        "system": SYSTEM_PROMPT,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": llm["temperature"],
        },
    }
