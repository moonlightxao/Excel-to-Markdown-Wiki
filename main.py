"""CLI entry point for Excel to Markdown Wiki converter."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from config import apply_cli_overrides, load_config, save_default_config
from excel_parser import ExcelParser
from md_writer import MDWriter
from models import FaultCase
from prompt_template import SYSTEM_PROMPT, build_prompt

logger = logging.getLogger(__name__)

SAMPLE_DATA_PATH = Path(__file__).parent / "sample_data" / "demo_fault_data.xlsx"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Excel to Markdown Wiki 自动化工具 — 解析关联 Excel 生成运维预案"
    )
    parser.add_argument("--config", type=Path, default=None, help="配置文件路径 (默认: ./config.yaml)")
    parser.add_argument("--excel", type=str, default=None, help="Excel 文件路径 (覆盖配置)")
    parser.add_argument("--output", type=str, default=None, help="输出目录 (覆盖配置)")
    parser.add_argument("--model", type=str, default=None, help="LLM 模型名称 (覆盖配置)")
    parser.add_argument("--concurrency", type=int, default=None, help="并发数")
    parser.add_argument("--init", action="store_true", help="生成默认配置文件 config.yaml 并退出")
    parser.add_argument("--check", action="store_true", help="检查 LLM 服务可用性并退出")
    parser.add_argument("--dry-run", action="store_true", help="仅解析 Excel，不调用 LLM")
    parser.add_argument("--save-prompts", action="store_true", help="保存提示词到输出目录（可配合外部大模型使用）")
    parser.add_argument("--sample", action="store_true", help="使用内置示例数据")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志输出")
    return parser.parse_args()


def setup_logging(config: dict, verbose: bool) -> None:
    level = logging.DEBUG if verbose else getattr(logging, config.get("logging", {}).get("level", "INFO"))
    log_file = config.get("logging", {}).get("file", "excel2md.log")

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


def print_fault_case(fc: FaultCase, index: int) -> None:
    """Pretty-print a FaultCase for dry-run verification."""
    print(f"\n{'='*60}")
    print(f"Fault Case #{index + 1}")
    print(f"{'='*60}")
    print(f"  故障ID:    {fc.phenomenon.fault_id}")
    print(f"  现象名称:  {fc.phenomenon.name}")
    print(f"  描述:      {fc.phenomenon.description}")
    print(f"  引用定界IDs: {fc.phenomenon.diagnostic_ids}")
    print(f"  已关联定界:  {len(fc.diagnostics)} 个")
    for d in fc.diagnostics:
        print(f"    - [{d.diagnostic_id}] {d.name}")
        print(f"      恢复方案IDs: {d.recovery_ids}")
    print(f"  已关联恢复:  {len(fc.recoveries)} 个")
    for r in fc.recoveries:
        print(f"    - [{r.recovery_id}] {r.name} (工具: {r.tool})")
    if fc.missing_ids:
        print(f"  ⚠ 缺失IDs: {fc.missing_ids}")
    print(f"  数据完整:  {'是' if not fc.has_missing_data else '否'}")


def _save_prompts(cases: list[FaultCase], config: dict) -> None:
    """Save each case's prompt to the output directory."""
    from md_writer import MDWriter

    output_dir = Path(config["output"]["directory"])
    output_dir.mkdir(parents=True, exist_ok=True)
    gen_suggestions = config.get("llm", {}).get("generate_missing_suggestions", False)

    # Save system prompt once
    sys_prompt_path = output_dir / "system_prompt.txt"
    sys_prompt_path.write_text(SYSTEM_PROMPT, encoding="utf-8")
    print(f"  保存系统提示词: {sys_prompt_path.name}")

    for fc in cases:
        prompt = build_prompt(fc, generate_suggestions=gen_suggestions)
        filename = f"{fc.phenomenon.fault_id}_{MDWriter.sanitize_filename(fc.phenomenon.name)}_prompt.txt"
        content = f"=== System Prompt ===\n{SYSTEM_PROMPT}\n\n=== User Prompt ===\n{prompt}"
        (output_dir / filename).write_text(content, encoding="utf-8")
        print(f"  保存: {filename}")

    print(f"\n已保存 {len(cases)} 个提示词到 {output_dir}/ 目录")


def main() -> int:
    args = parse_args()

    # --init: generate default config and exit
    if args.init:
        config_path = args.config or Path("config.yaml")
        save_default_config(config_path)
        print(f"已生成默认配置文件: {config_path}")
        print("请根据你的 Excel 文件修改列名映射后重新运行。")
        return 0

    # Load config
    config = load_config(args.config)
    config = apply_cli_overrides(config, args)

    # Setup logging
    setup_logging(config, args.verbose)

    # --check: verify LLM availability and exit
    if args.check:
        print("正在检查 LLM 服务...")
        try:
            from llm_client import LLMClient
            client = LLMClient(config)
            client.check_availability()
            print(f"✓ LLM 服务可用，模型: {config['llm']['model']}")
            return 0
        except Exception as e:
            print(f"✗ LLM 服务不可用: {e}")
            return 1

    # Determine Excel file path
    if args.sample:
        excel_path = SAMPLE_DATA_PATH
        if not excel_path.exists():
            print(f"错误: 示例数据文件不存在: {excel_path}")
            print("请先运行创建示例数据的脚本。")
            return 1
    else:
        excel_path = Path(config["excel"]["file_path"])

    if not excel_path.exists():
        print(f"错误: Excel 文件不存在: {excel_path}")
        print("使用 --sample 运行示例数据，或使用 --excel 指定文件路径。")
        return 1

    print(f"正在解析 Excel 文件: {excel_path}")

    # Parse Excel
    parser = ExcelParser(config)
    try:
        cases = parser.parse(excel_path)
    except Exception as e:
        logger.error(f"Excel 解析失败: {e}")
        print(f"错误: Excel 解析失败 — {e}")
        return 1

    print(f"解析完成: 共 {len(cases)} 个故障案例")
    missing_count = sum(1 for c in cases if c.has_missing_data)
    if missing_count:
        print(f"  其中 {missing_count} 个存在缺失关联数据")

    # Dry-run mode: print results and save prompts
    if args.dry_run:
        print("\n--- DRY-RUN 模式: 不调用 LLM ---\n")
        for i, fc in enumerate(cases):
            print_fault_case(fc, i)
        print(f"\n{'='*60}")
        print(f"总计: {len(cases)} 个案例, {missing_count} 个有缺失数据")

        # Save prompts for external LLM use
        print(f"\n保存提示词到 {config['output']['directory']}/ 目录...")
        _save_prompts(cases, config)
        print("如需生成 Markdown，请去掉 --dry-run 参数运行。")
        return 0

    # Save-prompts mode: build prompts and save, no LLM
    if args.save_prompts:
        print(f"\n保存提示词到 {config['output']['directory']}/ 目录...")
        _save_prompts(cases, config)
        return 0

    # Full mode: LLM generation
    from llm_client import LLMClient, LLMUnavailableError, LLMGenerationError
    from prompt_template import build_prompt

    # Check LLM availability
    print("正在检查 LLM 服务...")
    try:
        llm_client = LLMClient(config)
        llm_client.check_availability()
        print(f"✓ LLM 服务就绪，模型: {config['llm']['model']}")
    except LLMUnavailableError as e:
        print(f"✗ LLM 服务不可用: {e}")
        return 1

    # Process each case
    md_writer = MDWriter(config)
    results: list[dict] = []
    success_count = 0
    fail_count = 0

    print(f"\n开始生成 Markdown 预案（共 {len(cases)} 个）...\n")

    for i, fc in enumerate(cases):
        fault_label = f"[{fc.phenomenon.fault_id}] {fc.phenomenon.name}"
        print(f"  [{i+1}/{len(cases)}] 处理 {fault_label}...", end=" ", flush=True)

        try:
            gen_suggestions = config.get("llm", {}).get("generate_missing_suggestions", False)
            prompt = build_prompt(fc, generate_suggestions=gen_suggestions)
            markdown_content = llm_client.generate(prompt)

            # Validate generated markdown
            warnings = MDWriter.validate_markdown(markdown_content)
            if warnings:
                for w in warnings:
                    logger.warning(f"Markdown 验证警告 [{fault_label}]: {w}")

            # Write file
            output_path = md_writer.write(fc, markdown_content)
            print(f"→ {output_path.name}")
            results.append({
                "fault_id": fc.phenomenon.fault_id,
                "name": fc.phenomenon.name,
                "status": "success",
                "output_path": str(output_path),
            })
            success_count += 1

        except LLMGenerationError as e:
            print(f"→ 失败: {e}")
            logger.error(f"生成失败 [{fault_label}]: {e}")
            results.append({
                "fault_id": fc.phenomenon.fault_id,
                "name": fc.phenomenon.name,
                "status": "failed",
                "error": str(e),
            })
            fail_count += 1

        except Exception as e:
            print(f"→ 异常: {e}")
            logger.error(f"处理异常 [{fault_label}]: {e}")
            results.append({
                "fault_id": fc.phenomenon.fault_id,
                "name": fc.phenomenon.name,
                "status": "failed",
                "error": str(e),
            })
            fail_count += 1

    # Write summary index
    summary_path = md_writer.write_summary(results)

    # Print summary
    print(f"\n{'='*60}")
    print(f"处理完成")
    print(f"{'='*60}")
    print(f"  总计:     {len(cases)} 个")
    print(f"  成功:     {success_count} 个")
    print(f"  失败:     {fail_count} 个")
    if missing_count:
        print(f"  缺失数据: {missing_count} 个")
    print(f"  输出目录: {config['output']['directory']}/")
    print(f"  索引文件: {summary_path}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
