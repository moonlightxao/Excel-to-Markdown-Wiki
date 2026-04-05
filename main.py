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
        help="指定 Excel 文件路径，覆盖 config.py 中的配置",
    )
    return parser.parse_args()


def _run_similarity_analysis(
    phenomena: dict,
    diagnostics: dict,
    recoveries: dict,
    llm_client,
    config: dict,
) -> dict[str, list[str]]:
    """Run LLM-based similarity analysis and return merge_map.

    Returns:
        A dict mapping high-level fault_id to list of low-level fault_ids
        whose diagnostics/recoveries should be merged in.
    """
    from similarity import (
        SIMILARITY_SYSTEM_PROMPT,
        build_similarity_prompt,
        parse_similarity_response,
        resolve_merge_directions,
    )

    sim_cfg = config.get("similarity_analysis", {})
    max_phenomena = sim_cfg.get("max_phenomena", 50)

    if len(phenomena) > max_phenomena:
        logger.warning(
            "Too many phenomena (%d > %d), skipping similarity analysis",
            len(phenomena),
            max_phenomena,
        )
        print(f"  跳过相似性分析：故障现象数量 ({len(phenomena)}) 超过上限 ({max_phenomena})")
        return {}

    print("  正在构建相似性分析提示...")
    sim_prompt = build_similarity_prompt(phenomena, diagnostics, recoveries)

    print("  正在调用 LLM 进行相似性分析...")
    try:
        sim_response = llm_client.generate(sim_prompt, system_prompt=SIMILARITY_SYSTEM_PROMPT)
    except Exception as e:
        logger.error("Similarity analysis LLM call failed: %s", e)
        print(f"  相似性分析失败: {e}")
        return {}

    print("  正在解析相似性分析结果...")
    sim_groups = parse_similarity_response(sim_response)
    if not sim_groups:
        print("  未发现相似的故障现象")
        return {}

    print(f"  发现 {len(sim_groups)} 组相似故障现象")
    for g in sim_groups:
        print(f"    组 {g.group_id}: {', '.join(g.phenomenon_ids)} — {g.similarity_reason}")

    merge_map = resolve_merge_directions(sim_groups, phenomena)
    if merge_map:
        print("  合并方向:")
        for high_id, low_ids in merge_map.items():
            low_names = [f"{lid}({phenomena[lid].name})" for lid in low_ids if lid in phenomena]
            print(f"    {high_id} ← {', '.join(low_names)}")
    else:
        print("  按层级规则，无符合条件的合并")

    return merge_map


def _inject_merged_data(
    cases: list[FaultCase],
    merge_map: dict[str, list[str]],
    phenomena: dict,
    diagnostics: dict,
    recoveries: dict,
) -> None:
    """Inject merged diagnostics and recoveries into FaultCase objects.

    For each case whose fault_id appears in merge_map, resolve the
    source phenomena's diagnostics and recoveries and store them in
    merged_diagnostics / merged_recoveries.
    """
    for case in cases:
        fault_id = case.phenomenon.fault_id
        src_ids = merge_map.get(fault_id, [])
        if not src_ids:
            continue

        for src_id in src_ids:
            src_phenom = phenomena.get(src_id)
            if not src_phenom:
                continue

            # Resolve source diagnostics
            for diag_id in src_phenom.diagnostic_ids:
                d = diagnostics.get(diag_id)
                if not d:
                    continue

                # Resolve source recoveries under this diagnostic
                src_recoveries = []
                for rid in d.recovery_ids:
                    r = recoveries.get(rid)
                    if r:
                        src_recoveries.append({
                            "recovery_id": r.recovery_id,
                            "name": r.name,
                            "steps": r.steps,
                            "tool": r.tool,
                        })

                case.merged_diagnostics.append({
                    "source_fault_id": src_phenom.fault_id,
                    "source_fault_name": src_phenom.name,
                    "diagnostic_id": d.diagnostic_id,
                    "name": d.name,
                    "steps": d.steps,
                    "tool": d.tool,
                    "result": d.result,
                    "recoveries": src_recoveries,
                })

            # Also track source recoveries at the top level for easy reference
            for rid in src_phenom.diagnostic_ids:
                d = diagnostics.get(rid)
                if d:
                    for rec_id in d.recovery_ids:
                        r = recoveries.get(rec_id)
                        if r and not any(
                            mr["recovery_id"] == r.recovery_id
                            for mr in case.merged_recoveries
                        ):
                            case.merged_recoveries.append({
                                "source_fault_id": src_phenom.fault_id,
                                "source_fault_name": src_phenom.name,
                                "recovery_id": r.recovery_id,
                                "name": r.name,
                                "steps": r.steps,
                                "tool": r.tool,
                            })


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
    config = load_config()

    # CLI override for Excel file path
    if args.excel:
        config["excel"]["file_path"] = args.excel

    # Determine Excel file path
    excel_path = Path(config["excel"]["file_path"])
    if not excel_path.exists():
        print(f"错误: Excel 文件不存在: {excel_path}")
        print("请在 config.py 中配置正确的 excel.file_path。")
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

    # --- Similarity analysis (optional) ---
    merge_map: dict[str, list[str]] = {}
    sim_enabled = config.get("similarity_analysis", {}).get("enabled", False)
    if sim_enabled and len(phenomena) > 1:
        print("\n--- 故障现象相似性分析 ---\n")
        merge_map = _run_similarity_analysis(
            phenomena, diagnostics, recoveries, llm_client, config,
        )

    # Build fault cases with foreign key resolution
    cases = parser.parse(excel_path)
    missing_count = sum(1 for c in cases if c.has_missing_data)
    if missing_count:
        print(f"  其中 {missing_count} 个案例存在缺失关联数据")

    # Inject merged data from similarity analysis
    if merge_map:
        _inject_merged_data(cases, merge_map, phenomena, diagnostics, recoveries)

    # Process each case
    md_writer = MDWriter(config)
    results: list[dict] = []
    success_count = 0
    fail_count = 0

    print(f"\n开始生成恢复预案（共 {len(cases)} 个）...\n")

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
    if merge_map:
        print(f"  相似合并: {sum(len(v) for v in merge_map.values())} 组")
    print(f"  输出目录: {config['output']['directory']}/")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
