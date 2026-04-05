"""Fault phenomenon similarity analysis via LLM.

Sends all fault phenomena to the LLM in a single batch call, asks it to
identify groups of similar phenomena, then determines merge directions
based on layer hierarchy rules.
"""

from __future__ import annotations

import json
import logging
import re

from models import (
    DiagnosticMethod,
    FaultPhenomenon,
    RecoveryPlan,
    SimilarityGroup,
    is_higher_layer,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt for similarity analysis
# ---------------------------------------------------------------------------

SIMILARITY_SYSTEM_PROMPT = (
    "你是一名运维故障分析专家。你的任务是分析一组故障现象之间是否存在描述上的相似性。\n"
    "\n"
    "请严格遵守以下规则：\n"
    "1. 仅输出 JSON 数组，不要输出任何其他文字说明或解释。\n"
    "2. 每个相似组包含：group_id（组编号）、phenomenon_ids（相似故障的 ID 列表）、"
    "similarity_reason（相似原因说明）、shared_symptoms（共享的症状关键词列表）。\n"
    "3. 两个故障现象只要有部分描述重叠或语义相近，就应归为同一相似组。\n"
    "4. 一个故障现象可以出现在多个相似组中。\n"
    "5. 如果没有任何相似的故障现象，输出空数组 []。\n"
    "6. 请将 JSON 放在 ```json 代码块中输出。\n"
)

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def build_similarity_prompt(
    phenomena: dict[str, FaultPhenomenon],
    diagnostics: dict[str, DiagnosticMethod],
    recoveries: dict[str, RecoveryPlan],
) -> str:
    """Build the prompt for similarity analysis.

    Serializes all phenomena with their resolved diagnostics and recovery
    IDs into a JSON payload for the LLM.
    """
    items = []
    for fault_id, p in phenomena.items():
        # Resolve diagnostic names and their recovery IDs
        diag_info = []
        for did in p.diagnostic_ids:
            d = diagnostics.get(did)
            if d:
                diag_info.append({
                    "diagnostic_id": did,
                    "name": d.name,
                    "recovery_ids": d.recovery_ids,
                })
            else:
                diag_info.append({"diagnostic_id": did, "name": "[未找到]", "recovery_ids": []})

        items.append({
            "fault_id": fault_id,
            "name": p.name,
            "description": p.description,
            "layer": p.layer,
            "diagnostics": diag_info,
        })

    data_json = json.dumps(items, ensure_ascii=False, indent=2)

    return (
        "以下是所有故障现象的数据（含故障表现层级和已有的定界手段/恢复方案）：\n"
        "\n"
        f"```json\n{data_json}\n```\n"
        "\n"
        "请分析这些故障现象之间的描述相似性，找出描述有重叠或语义相近的故障组。"
        "输出 JSON 数组，每个元素代表一组相似的故障现象。"
    )


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------


def parse_similarity_response(llm_output: str) -> list[SimilarityGroup]:
    """Parse the LLM output into a list of SimilarityGroup objects.

    Extracts JSON from ```json code blocks, with fallback to raw text.
    """
    # Try to extract JSON from code block
    json_match = re.search(r"```json\s*(.*?)\s*```", llm_output, re.DOTALL)
    json_text = json_match.group(1) if json_match else llm_output.strip()

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        logger.error("Failed to parse LLM similarity response as JSON")
        return []

    if not isinstance(data, list):
        logger.error("LLM similarity response is not a JSON array")
        return []

    groups: list[SimilarityGroup] = []
    for i, item in enumerate(data):
        try:
            group = SimilarityGroup(
                group_id=item.get("group_id", f"G{i + 1}"),
                phenomenon_ids=item.get("phenomenon_ids", []),
                similarity_reason=item.get("similarity_reason", ""),
                shared_symptoms=item.get("shared_symptoms", []),
            )
            if len(group.phenomenon_ids) >= 2:
                groups.append(group)
        except Exception as e:
            logger.warning("Skipping malformed similarity group: %s", e)
            continue

    return groups


# ---------------------------------------------------------------------------
# Merge direction resolver (pure logic, no LLM)
# ---------------------------------------------------------------------------


def resolve_merge_directions(
    groups: list[SimilarityGroup],
    phenomena: dict[str, FaultPhenomenon],
) -> dict[str, list[str]]:
    """Determine merge directions based on layer hierarchy rules.

    Rules:
    1. Lower-layer diagnostics/recoveries merge INTO higher-layer 预案.
    2. Same-layer phenomena do NOT merge.
    3. Higher-layer never merges into lower-layer.

    Returns:
        A dict mapping each high-level fault_id to a list of low-level
        fault_ids whose diagnostics and recoveries should be merged in.
    """
    merge_map: dict[str, list[str]] = {}

    for group in groups:
        # Collect all valid fault_ids with their layers
        members = []
        for fid in group.phenomenon_ids:
            p = phenomena.get(fid)
            if p and p.layer:
                members.append(p)

        if len(members) < 2:
            continue

        # Compare each pair
        for i, p_high in enumerate(members):
            for p_low in members[i + 1:]:
                cmp = is_higher_layer(p_high.layer, p_low.layer)
                if cmp is True:
                    # p_high is higher → merge p_low into p_high
                    merge_map.setdefault(p_high.fault_id, [])
                    if p_low.fault_id not in merge_map[p_high.fault_id]:
                        merge_map[p_high.fault_id].append(p_low.fault_id)
                elif cmp is False:
                    # p_low is actually higher → merge p_high into p_low
                    merge_map.setdefault(p_low.fault_id, [])
                    if p_high.fault_id not in merge_map[p_low.fault_id]:
                        merge_map[p_low.fault_id].append(p_high.fault_id)
                # cmp is None → same layer, no merge (Rule 2)

    return merge_map
