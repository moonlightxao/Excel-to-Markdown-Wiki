"""Configuration management with layered defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "excel": {
        "file_path": "data/input.xlsx",
        "sheets": {
            "fault_phenomenon": {
                "sheet_name": "故障现象场景清单模版",
                "id_column": "编号",
                "name_column": "故障现象",
                "description_column": "现象描述",
                "diagnostic_ref_column": "定界方法",
                "category_column": "分类",
                "perception_method_column": "故障感知手段",
                "has_perception_column": "是否已有感知手段",
                "layer_column": "故障表现层级",
            },
            "diagnostic_method": {
                "sheet_name": "定界手段模板",
                "id_column": "编号",
                "name_column": "定界方法名称",
                "steps_column": "详细定界方法",
                "recovery_ref_column": "恢复方案建议",
                "tool_column": "定界工具",
                "result_column": "定界结果",
            },
            "recovery_plan": {
                "sheet_name": "恢复方案模板",
                "id_column": "编号",
                "name_column": "应对方案名",
                "steps_column": "方案概述",
                "tool_column": "恢复工具",
            },
        },
        "id_separator": ",",
        "skip_empty_rows": True,
    },
    "llm": {
        "provider": "ollama",
        "base_url": "http://localhost:11434",
        "model": "qwen2.5:7b",
        "api_key": "",
        "timeout_seconds": 300,
        "max_retries": 3,
        "retry_delay_seconds": 5,
        "concurrency": 1,
        "temperature": 0.3,
        "stream": False,
        "enable_thinking": False,
        "generate_missing_suggestions": True,
    },
    "output": {
        "directory": "output",
        "filename_pattern": "{fault_id}_{phenomenon_name}.md",
        "overwrite_existing": True,
    },
    "similarity_analysis": {
        "enabled": False,
        "timeout_seconds": 300,
        "max_phenomena": 50,
    },
    "logging": {
        "level": "INFO",
        "file": "excel2md.log",
    },
}


def load_config() -> dict[str, Any]:
    """Load config from DEFAULT_CONFIG.

    Users can modify DEFAULT_CONFIG directly in this file to change settings.
    """
    return deep_copy_dict(DEFAULT_CONFIG)


def deep_copy_dict(d: dict) -> dict:
    """Simple deep copy for dicts of basic types."""
    result = {}
    for key, value in d.items():
        if isinstance(value, dict):
            result[key] = deep_copy_dict(value)
        elif isinstance(value, list):
            result[key] = list(value)
        else:
            result[key] = value
    return result
