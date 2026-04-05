"""Excel parser module — reads 3 Excel sheets and produces FaultCase objects.

Sheets (configured via config["excel"]["sheets"]):
  1. fault_phenomenon  -> FaultPhenomenon
  2. diagnostic_method -> DiagnosticMethod
  3. recovery_plan     -> RecoveryPlan

Foreign-key relationships:
  FaultPhenomenon.diagnostic_ids  --> DiagnosticMethod.diagnostic_id
  DiagnosticMethod.recovery_ids   --> RecoveryPlan.recovery_id
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from models import DiagnosticMethod, FaultCase, FaultPhenomenon, RecoveryPlan

logger = logging.getLogger(__name__)


class ExcelParser:
    """Parse an Excel workbook into a list of fully-resolved FaultCase objects."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.excel_cfg = config.get("excel", {})
        self.sheets_cfg = self.excel_cfg.get("sheets", {})
        self.id_separator = self.excel_cfg.get("id_separator", ",")
        self.skip_empty_rows = self.excel_cfg.get("skip_empty_rows", True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, file_path: Path) -> list[FaultCase]:
        """Read an Excel file and return a list of FaultCase objects."""
        phenomena, diagnostics, recoveries = self.parse_sheets_raw(file_path)

        # Resolve foreign keys and build FaultCase list
        cases = self._resolve_foreign_keys(phenomena, diagnostics, recoveries)
        logger.info("Built %d fault cases", len(cases))
        return cases

    def parse_sheets_raw(
        self, file_path: Path
    ) -> tuple[dict[str, FaultPhenomenon], dict[str, DiagnosticMethod], dict[str, RecoveryPlan]]:
        """Read an Excel file and return raw parsed data from all three sheets.

        Unlike :meth:`parse`, this does **not** resolve foreign keys — it
        returns the three sheet-level dicts as-is, suitable for per-row
        Markdown generation.
        """
        file_path = Path(file_path)
        logger.info("Parsing Excel file (raw sheets): %s", file_path)

        fp_df = self._read_sheet(file_path, "fault_phenomenon")
        dm_df = self._read_sheet(file_path, "diagnostic_method")
        rp_df = self._read_sheet(file_path, "recovery_plan")

        phenomena = self._parse_fault_phenomena(fp_df)
        diagnostics = self._parse_diagnostics(dm_df)
        recoveries = self._parse_recoveries(rp_df)

        logger.info(
            "Parsed %d phenomena, %d diagnostics, %d recoveries",
            len(phenomena),
            len(diagnostics),
            len(recoveries),
        )
        return phenomena, diagnostics, recoveries

    # ------------------------------------------------------------------
    # Sheet reading
    # ------------------------------------------------------------------

    def _read_sheet(self, file_path: Path, sheet_key: str) -> pd.DataFrame:
        """Read a single sheet from the workbook and return a cleaned DataFrame.

        Performs column-name stripping, empty-row dropping, and NaN normalization.
        """
        sheet_cfg = self.sheets_cfg.get(sheet_key, {})
        sheet_name = sheet_cfg.get("sheet_name", sheet_key)

        try:
            df = pd.read_excel(
                file_path,
                sheet_name=sheet_name,
                engine="openpyxl",
                dtype=str,
            )
        except ValueError as exc:
            # Sheet not found — list available sheets for a helpful message
            try:
                xls = pd.ExcelFile(file_path, engine="openpyxl")
                available = xls.sheet_names
            except Exception:
                available = []
            raise ValueError(
                f"Sheet '{sheet_name}' (key='{sheet_key}') not found in "
                f"{file_path}. Available sheets: {available}"
            ) from exc

        # Strip whitespace from column names
        df.columns = [str(c).strip() for c in df.columns]

        # Normalize NaN across the entire DataFrame
        df = df.fillna("")

        # Drop completely empty rows
        df = df.dropna(how="all")

        # Additional pass: drop rows where every stringified cell is empty
        mask = df.apply(lambda row: all(str(v).strip() == "" for v in row), axis=1)
        df = df[~mask].reset_index(drop=True)

        logger.debug(
            "Sheet '%s' loaded: %d rows, %d columns", sheet_name, len(df), len(df.columns)
        )
        return df

    # ------------------------------------------------------------------
    # Parsing helpers — one per sheet
    # ------------------------------------------------------------------

    def _parse_fault_phenomena(self, df: pd.DataFrame) -> dict[str, FaultPhenomenon]:
        """Parse the fault_phenomenon sheet into a dict keyed by fault_id."""
        cfg = self.sheets_cfg.get("fault_phenomenon", {})
        id_col = self._resolve_column(df, cfg, "id_column")
        name_col = self._resolve_column(df, cfg, "name_column")
        desc_col = self._resolve_column(df, cfg, "description_column")
        diag_ref_col = self._resolve_column(df, cfg, "diagnostic_ref_column")
        cat_col = self._try_resolve_column(df, cfg, "category_column")
        perc_col = self._try_resolve_column(df, cfg, "perception_method_column")
        has_perc_col = self._try_resolve_column(df, cfg, "has_perception_column")

        result: dict[str, FaultPhenomenon] = {}
        for _, row in df.iterrows():
            fault_id = str(row.get(id_col, "")).strip()
            if not fault_id:
                logger.warning("Skipping fault_phenomenon row with empty ID")
                continue

            raw_diag_ids = str(row.get(diag_ref_col, "")).strip()
            diagnostic_ids = self._split_id_list(raw_diag_ids, self.id_separator)

            result[fault_id] = FaultPhenomenon(
                fault_id=fault_id,
                name=str(row.get(name_col, "")).strip(),
                description=str(row.get(desc_col, "")).strip(),
                diagnostic_ids=diagnostic_ids,
                category=str(row.get(cat_col, "")).strip() if cat_col else "",
                perception_method=str(row.get(perc_col, "")).strip() if perc_col else "",
                has_perception=str(row.get(has_perc_col, "")).strip() if has_perc_col else "",
            )

        return result

    def _parse_diagnostics(self, df: pd.DataFrame) -> dict[str, DiagnosticMethod]:
        """Parse the diagnostic_method sheet into a dict keyed by diagnostic_id."""
        cfg = self.sheets_cfg.get("diagnostic_method", {})
        id_col = self._resolve_column(df, cfg, "id_column")
        name_col = self._resolve_column(df, cfg, "name_column")
        steps_col = self._resolve_column(df, cfg, "steps_column")
        rec_ref_col = self._resolve_column(df, cfg, "recovery_ref_column")
        tool_col = self._try_resolve_column(df, cfg, "tool_column")
        result_col = self._try_resolve_column(df, cfg, "result_column")

        result: dict[str, DiagnosticMethod] = {}
        for _, row in df.iterrows():
            diag_id = str(row.get(id_col, "")).strip()
            if not diag_id:
                logger.warning("Skipping diagnostic_method row with empty ID")
                continue

            raw_rec_ids = str(row.get(rec_ref_col, "")).strip()
            recovery_ids = self._split_id_list(raw_rec_ids, self.id_separator)

            result[diag_id] = DiagnosticMethod(
                diagnostic_id=diag_id,
                name=str(row.get(name_col, "")).strip(),
                steps=str(row.get(steps_col, "")).strip(),
                recovery_ids=recovery_ids,
                tool=str(row.get(tool_col, "")).strip() if tool_col else "",
                result=str(row.get(result_col, "")).strip() if result_col else "",
            )

        return result

    def _parse_recoveries(self, df: pd.DataFrame) -> dict[str, RecoveryPlan]:
        """Parse the recovery_plan sheet into a dict keyed by recovery_id."""
        cfg = self.sheets_cfg.get("recovery_plan", {})
        id_col = self._resolve_column(df, cfg, "id_column")
        name_col = self._resolve_column(df, cfg, "name_column")
        steps_col = self._resolve_column(df, cfg, "steps_column")
        tool_col = self._try_resolve_column(df, cfg, "tool_column")

        result: dict[str, RecoveryPlan] = {}
        for _, row in df.iterrows():
            rec_id = str(row.get(id_col, "")).strip()
            if not rec_id:
                logger.warning("Skipping recovery_plan row with empty ID")
                continue

            raw_steps = str(row.get(steps_col, "")).strip()
            steps = [s.strip() for s in raw_steps.split("\n") if s.strip()] if raw_steps else []

            result[rec_id] = RecoveryPlan(
                recovery_id=rec_id,
                name=str(row.get(name_col, "")).strip(),
                steps=steps,
                raw_steps=raw_steps,
                tool=str(row.get(tool_col, "")).strip() if tool_col else "",
            )

        return result

    # ------------------------------------------------------------------
    # Foreign-key resolution
    # ------------------------------------------------------------------

    def _resolve_foreign_keys(
        self,
        phenomena: dict[str, FaultPhenomenon],
        diagnostics: dict[str, DiagnosticMethod],
        recoveries: dict[str, RecoveryPlan],
    ) -> list[FaultCase]:
        """Walk every phenomenon and resolve its diagnostic and recovery references.

        Missing IDs are tracked in FaultCase.missing_ids as
        ``[缺失关联数据：ID xxxx]``.
        """
        cases: list[FaultCase] = []

        for fault_id, phenom in phenomena.items():
            missing_ids: list[str] = []
            resolved_diagnostics: list[DiagnosticMethod] = []
            resolved_recoveries: list[RecoveryPlan] = []

            for diag_id in phenom.diagnostic_ids:
                if diag_id not in diagnostics:
                    tag = f"[缺失关联数据：ID {diag_id}]"
                    missing_ids.append(tag)
                    logger.warning(
                        "Fault '%s' references missing diagnostic '%s'",
                        fault_id,
                        diag_id,
                    )
                    continue

                diag = diagnostics[diag_id]
                resolved_diagnostics.append(diag)

                # Resolve recovery IDs referenced by this diagnostic
                for rec_id in diag.recovery_ids:
                    if rec_id not in recoveries:
                        tag = f"[缺失关联数据：ID {rec_id}]"
                        missing_ids.append(tag)
                        logger.warning(
                            "Diagnostic '%s' references missing recovery '%s'",
                            diag_id,
                            rec_id,
                        )
                        continue

                    resolved_recoveries.append(recoveries[rec_id])

            cases.append(
                FaultCase(
                    phenomenon=phenom,
                    diagnostics=resolved_diagnostics,
                    recoveries=resolved_recoveries,
                    missing_ids=missing_ids,
                )
            )

        return cases

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split_id_list(raw: str, separator: str) -> list[str]:
        """Split a multi-value ID cell into a list of trimmed, non-empty strings."""
        if not raw:
            return []
        return [
            token.strip()
            for token in raw.split(separator)
            if token.strip()
        ]

    def _resolve_column(
        self,
        df: pd.DataFrame,
        sheet_cfg: dict[str, Any],
        cfg_key: str,
    ) -> str:
        """Return the actual column name in *df* for the given config key.

        1. Try the exact name from config.
        2. Fall back to fuzzy matching by keyword heuristics.
        3. Raise ValueError if nothing matches.
        """
        desired_name = sheet_cfg.get(cfg_key, "")

        # Exact match
        if desired_name and desired_name in df.columns:
            return desired_name

        # Fuzzy fallback
        candidate = self._fuzzy_match_column(df, cfg_key, desired_name)
        if candidate is not None:
            logger.warning(
                "Column '%s' (config key '%s') not found; "
                "auto-detected as '%s'",
                desired_name,
                cfg_key,
                candidate,
            )
            return candidate

        # Nothing found
        raise ValueError(
            f"Column '{desired_name}' (config key '{cfg_key}') not found in "
            f"DataFrame. Available columns: {list(df.columns)}"
        )

    def _try_resolve_column(
        self,
        df: pd.DataFrame,
        sheet_cfg: dict[str, Any],
        cfg_key: str,
    ) -> str | None:
        """Like _resolve_column but returns None instead of raising."""
        desired_name = sheet_cfg.get(cfg_key, "")
        if not desired_name:
            return None
        if desired_name in df.columns:
            return desired_name
        candidate = self._fuzzy_match_column(df, cfg_key, desired_name)
        if candidate is not None:
            logger.warning(
                "Column '%s' (config key '%s') not found; "
                "auto-detected as '%s'",
                desired_name,
                cfg_key,
                candidate,
            )
            return candidate
        logger.debug(
            "Optional column '%s' (config key '%s') not found, skipping",
            desired_name,
            cfg_key,
        )
        return None

    @staticmethod
    def _fuzzy_match_column(
        df: pd.DataFrame,
        cfg_key: str,
        desired_name: str,
    ) -> str | None:
        """Attempt to find a column in *df* by keyword heuristics.

        Each config key maps to a set of Chinese/English keywords that are
        likely to appear in a reasonable column name.
        """
        keyword_map: dict[str, list[str]] = {
            "id_column": ["ID", "id", "编号"],
            "name_column": ["名称", "名", "现象", "手段", "方案"],
            "description_column": ["描述", "说明"],
            "steps_column": ["步骤", "执行", "详细"],
            "diagnostic_ref_column": ["定界", "手段", "诊断", "方法"],
            "recovery_ref_column": ["恢复", "方案", "建议"],
            "type_column": ["类型", "分类"],
            "category_column": ["分类", "视角"],
            "perception_method_column": ["感知", "监控"],
            "has_perception_column": ["已有", "感知"],
            "tool_column": ["工具", "平台"],
            "result_column": ["结果"],
        }

        keywords = keyword_map.get(cfg_key)
        if not keywords:
            return None

        # Build a secondary hint from the desired name itself
        extra_hints = [ch for ch in desired_name if '\u4e00' <= ch <= '\u9fff']

        for col in df.columns:
            col_lower = col.lower()
            # Check keyword-based match
            for kw in keywords:
                if kw.lower() in col_lower:
                    return col
            # Check if any character from the desired name appears in the column
            for hint in extra_hints:
                if hint in col:
                    return col

        return None
