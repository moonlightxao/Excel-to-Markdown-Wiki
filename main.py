"""CLI entry point for Excel to Markdown Wiki converter."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from config import load_config
from excel_parser import ExcelParser
from md_writer import MDWriter, SheetsMDWriter
from models import FaultCase
from prompt_template import build_prompt

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Excel to Markdown Wiki 自动化工具 — 解析关联 Excel 生成运维预案",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--sheets",
        action="store_true",
        help="生成故障现象、定界手段、恢复方案 Markdown（不需要 LLM）",
    )
    group.add_argument(
        "--full",
        action="store_true",
        help="全量生成：故障现象、定界手段、恢复方案 + 恢复预案（需要 LLM）",
    )
    parser.add_argument(
        "--excel",
        type=str,
        default=None,
        help="指定 Excel 文件路径，覆盖 config.yaml 中的配置",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("excel2md.log", encoding="utf-8"),
        ],
    )

    # Load config
    config = load_config(Path("config.yaml"))

    # CLI override for Excel file path
    if args.excel:
        config["excel"]["file_path"] = args.excel

    # Determine Excel file path
    excel_path = Path(config["excel"]["file_path"])
    if not excel_path.exists():
        print(f"错误: Excel 文件不存在: {excel_path}")
        print("请在 config.yaml 中配置正确的 excel.file_path。")
        return 1

    print(f"正在解析 Excel 文件: {excel_path}")

    # Parse Excel
    parser = ExcelParser(config)
    try:
        phenomena, diagnostics, recoveries = parser.parse_sheets_raw(excel_path)
    except Exception as e:
        logger.error("Excel 解析失败: %s", e)
        print(f"错误: Excel 解析失败 — {e}")
        return 1

    print(f"解析完成: {len(phenomena)} 个故障现象, {len(diagnostics)} 个定界手段, {len(recoveries)} 个恢复方案")

    # Always generate per-sheet Markdown files
    print("\n--- 生成故障现象、定界手段、恢复方案 Markdown ---\n")
    sheets_writer = SheetsMDWriter(base_dir=config["output"]["directory"])
    counts = sheets_writer.write_all(phenomena, diagnostics, recoveries)
    for subdir, count in counts.items():
        print(f"  {subdir}/: {count} 个文件")

    # --sheets mode: done
    if args.sheets:
        print(f"\n输出目录: {config['output']['directory']}/")
        return 0

    # --full mode: also generate LLM-based recovery plans
    print("\n--- 生成 LLM 恢复预案 ---\n")

    # Check LLM availability
    try:
        from llm_client import LLMUnavailableError, create_llm_client

        llm_client = create_llm_client(config)
        llm_client.check_availability()
        print(f"✓ LLM 服务就绪，模型: {config['llm']['model']}")
    except LLMUnavailableError as e:
        print(f"✗ LLM 服务不可用: {e}")
        return 1

    # Build fault cases with foreign key resolution
    cases = parser.parse(excel_path)
    missing_count = sum(1 for c in cases if c.has_missing_data)
    if missing_count:
        print(f"  其中 {missing_count} 个案例存在缺失关联数据")

    # Process each case
    md_writer = MDWriter(config)
    results: list[dict] = []
    success_count = 0
    fail_count = 0

    print(f"开始生成恢复预案（共 {len(cases)} 个）...\n")

    from llm_client import LLMGenerationError

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
                    logger.warning("Markdown 验证警告 [%s]: %s", fault_label, w)

            # Write file
            output_path = md_writer.write(fc, markdown_content)
            print(f"→ {output_path.name}")
            results.append({
                "fault_id": fc.phenomenon.fault_id,
                "phenomenon_name": fc.phenomenon.name,
                "filename": output_path.name,
                "success": True,
            })
            success_count += 1

        except (LLMGenerationError, Exception) as e:
            print(f"→ 失败: {e}")
            logger.error("生成失败 [%s]: %s", fault_label, e)
            results.append({
                "fault_id": fc.phenomenon.fault_id,
                "phenomenon_name": fc.phenomenon.name,
                "success": False,
                "error": str(e),
            })
            fail_count += 1

    # Write summary index
    md_writer.write_summary(results)

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

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
