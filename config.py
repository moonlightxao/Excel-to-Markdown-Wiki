"""Configuration management with YAML support and layered defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


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
        "base_url": "http://localhost:11434",
        "model": "qwen2.5:7b",
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
    "logging": {
        "level": "INFO",
        "file": "excel2md.log",
    },
}


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load config from YAML file merged with defaults."""
    config = deep_copy_dict(DEFAULT_CONFIG)
    if config_path and config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        config = deep_merge(config, user_config)
    return config


def save_default_config(path: Path) -> None:
    """Write DEFAULT_CONFIG to a YAML file for user reference."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Excel to Markdown Wiki 配置文件\n")
        f.write("# 修改此文件以匹配你的 Excel 列名和 LLM 设置\n\n")
        yaml.dump(DEFAULT_CONFIG, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base dict. Returns new dict."""
    result = deep_copy_dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


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


def apply_cli_overrides(config: dict[str, Any], args) -> dict[str, Any]:
    """Apply CLI argument overrides to config."""
    if args.excel:
        config["excel"]["file_path"] = args.excel
    if args.output:
        config["output"]["directory"] = args.output
    if args.model:
        config["llm"]["model"] = args.model
    if args.concurrency is not None:
        config["llm"]["concurrency"] = args.concurrency
    return config
