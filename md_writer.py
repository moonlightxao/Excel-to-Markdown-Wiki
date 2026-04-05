"""Markdown output module for Excel to Markdown Wiki converter.

Handles writing generated Markdown content to files, building filenames,
validating Markdown structure, and producing a summary index.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

from models import DiagnosticMethod, FaultCase, FaultPhenomenon, RecoveryPlan

logger = logging.getLogger(__name__)


class MDWriter:
    """Writes generated Markdown files and a summary index to disk.

    Parameters
    ----------
    config : dict
        Application configuration dictionary. Expected keys:
        - ``config["output"]["directory"]``: output directory path.
        - ``config["output"]["overwrite_existing"]``: whether to overwrite
          existing files (bool).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._output_dir: Path = Path(config["output"]["directory"])
        self._overwrite: bool = config["output"]["overwrite_existing"]
        self._output_dir.mkdir(parents=True, exist_ok=True)
        logger.info("MDWriter initialised; output directory: %s", self._output_dir.resolve())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write(self, fault_case: FaultCase, content: str) -> Path:
        """Write Markdown *content* to a file derived from *fault_case*.

        If the target file already exists and the overwrite policy is
        ``False``, the file is skipped and a warning is logged.

        Parameters
        ----------
        fault_case : FaultCase
            The fault case this content belongs to.
        content : str
            The full Markdown text to write.

        Returns
        -------
        Path
            The path to the written (or existing) file.
        """
        content = self.enrich_with_recovery_refs(fault_case, content)

        filename = self.build_filename(fault_case)
        filepath = self._output_dir / filename

        if filepath.exists() and not self._overwrite:
            logger.warning(
                "File already exists, skipping (overwrite=False): %s",
                filepath,
            )
            return filepath

        filepath.write_text(content, encoding="utf-8")
        logger.info("Wrote %s (%d bytes)", filepath, filepath.stat().st_size)
        return filepath

    @staticmethod
    def enrich_with_recovery_refs(fault_case: FaultCase, content: str) -> str:
        """Ensure each diagnostic section lists its associated recovery IDs.

        Scans *content* for ``### 定界手段 <ID>-...`` headings.  If a
        heading's section does not already contain a ``**关联恢复方案**``
        line, one is injected right after the heading based on
        ``DiagnosticMethod.recovery_ids`` from *fault_case*.

        Parameters
        ----------
        fault_case : FaultCase
            The fault case providing the diagnostic-to-recovery mapping.
        content : str
            The Markdown content produced by the LLM.

        Returns
        -------
        str
            The (possibly modified) Markdown content.
        """
        # Build a lookup: diagnostic_id -> list of recovery_ids
        diag_to_recoveries: dict[str, list[str]] = {
            d.diagnostic_id: d.recovery_ids for d in fault_case.diagnostics
        }

        # Match ### headings for diagnostic sections
        heading_pattern = re.compile(
            r"^(###\s*定界手段\s*)([A-Za-z]+\d+)\s*[-–—]\s*.+?$",
            re.MULTILINE,
        )

        lines = content.split("\n")
        result_lines: list[str] = []
        i = 0
        while i < len(lines):
            result_lines.append(lines[i])
            match = heading_pattern.match(lines[i])
            if match:
                diag_id = match.group(2)
                recovery_ids = diag_to_recoveries.get(diag_id, [])
                # Check if the next few lines already contain a recovery ref
                has_ref = False
                peek_end = min(i + 5, len(lines))
                for j in range(i + 1, peek_end):
                    if "**关联恢复方案**" in lines[j]:
                        has_ref = True
                        break
                    # Stop peeking at the next ### or ## heading
                    if re.match(r"^#{1,3}\s", lines[j]):
                        break

                if not has_ref:
                    ref_text = "、".join(recovery_ids) if recovery_ids else "无"
                    result_lines.append(f"\n**关联恢复方案**：{ref_text}")
            i += 1

        return "\n".join(result_lines)

    @staticmethod
    def build_filename(fault_case: FaultCase) -> str:
        """Construct a Markdown filename from a :class:`FaultCase`.

        The format is ``{fault_id}_{sanitized_phenomenon_name}.md``.

        Parameters
        ----------
        fault_case : FaultCase
            The fault case used to derive the filename.

        Returns
        -------
        str
            A sanitised filename ending in ``.md``.
        """
        fault_id = fault_case.phenomenon.fault_id
        phenomenon_name = MDWriter.sanitize_filename(
            fault_case.phenomenon.name,
        )
        return f"{fault_id}_{phenomenon_name}.md"

    @staticmethod
    def sanitize_filename(name: str) -> str:
        """Sanitise *name* for safe use in a filename.

        Rules
        -----
        * Keep ASCII letters, digits, underscores and hyphens.
        * Keep CJK characters (CJK Unified Ideographs, Hiragana, Katakana,
          Hangul Syllables, and CJK Compatibility).
        * Replace spaces with underscores.
        * Remove every other character.
        * Truncate the result to 80 characters.

        Parameters
        ----------
        name : str
            Raw phenomenon name string.

        Returns
        -------
        str
            A cleaned, filesystem-safe string (max 80 chars).
        """
        result: list[str] = []
        for ch in name:
            if ch == " ":
                result.append("_")
            elif (
                ch.isascii()
                and (ch.isalnum() or ch in ("_", "-"))
            ):
                result.append(ch)
            elif _is_cjk(ch):
                result.append(ch)
            # All other characters are dropped
        sanitized = "".join(result)
        return sanitized[:80]

    def write_summary(self, results: list[dict[str, Any]]) -> Path:
        """Generate ``index.md`` with links to every generated file.

        Parameters
        ----------
        results : list[dict]
            A list of result dictionaries. Each dict is expected to have
            at least a ``"filename"`` key and optionally ``"success"``
            (bool) and ``"fault_id"`` / ``"phenomenon_name"`` keys.

        Returns
        -------
        Path
            The path to the generated ``index.md``.
        """
        total = len(results)
        successful = sum(1 for r in results if r.get("success", False))
        failed = total - successful

        lines: list[str] = [
            "# Generated Wiki Index",
            "",
            "## Statistics",
            "",
            f"| Metric | Count |",
            f"|--------|-------|",
            f"| Total cases | {total} |",
            f"| Successful | {successful} |",
            f"| Failed | {failed} |",
            "",
            "## Files",
            "",
        ]

        for result in results:
            filename = result.get("filename", "")
            fault_id = result.get("fault_id", "UNKNOWN")
            phenomenon = result.get("phenomenon_name", "")
            success = result.get("success", False)

            if success and filename:
                lines.append(f"- [{filename}]({filename}) -- {fault_id}: {phenomenon}")
            else:
                error_msg = result.get("error", "unknown error")
                lines.append(
                    f"- **FAILED** {fault_id}: {phenomenon} ({error_msg})"
                )

        lines.append("")  # trailing newline

        index_path = self._output_dir / "index.md"

        if index_path.exists() and not self._overwrite:
            logger.warning(
                "index.md already exists, skipping (overwrite=False): %s",
                index_path,
            )
            return index_path

        index_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(
            "Wrote summary index (%d entries): %s", total, index_path,
        )
        return index_path

    @staticmethod
    def validate_markdown(content: str) -> list[str]:
        """Check *content* for common Markdown issues.

        Checks performed
        ----------------
        1. At least one ATX heading (``# ``) is present.
        2. Fenced code blocks (triple back-tick `````) come in pairs
           (i.e. an even number of occurrences).

        Parameters
        ----------
        content : str
            The Markdown text to validate.

        Returns
        -------
        list[str]
            A list of warning messages. An empty list means no issues
            were found.
        """
        warnings: list[str] = []

        # 1. Check for at least one heading
        heading_pattern = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
        if not heading_pattern.search(content):
            warnings.append("No Markdown headings (e.g. '# Title') found in content.")

        # 2. Check code block fences are balanced
        #    Match opening ``` that start a line (optionally with leading
        #    whitespace) and are followed by optional language tag but NOT
        #    followed by more back-tick characters (avoids counting ````
        #    style blocks incorrectly).
        fence_pattern = re.compile(r"^```", re.MULTILINE)
        fence_count = len(fence_pattern.findall(content))
        if fence_count % 2 != 0:
            warnings.append(
                f"Unclosed code block detected: found {fence_count} fence "
                "delimiter(s) (expected an even number)."
            )

        return warnings


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _is_cjk(character: str) -> bool:
    """Return ``True`` if *character* falls within common CJK Unicode ranges.

    Ranges covered
    --------------
    * CJK Unified Ideographs (U+4E00 – U+9FFF)
    * CJK Unified Ideographs Extension A (U+3400 – U+4DBF)
    * CJK Unified Ideographs Extension B (U+20000 – U+2A6DF)
    * CJK Compatibility Ideographs (U+F900 – U+FAFF)
    * Hiragana (U+3040 – U+309F)
    * Katakana (U+30A0 – U+30FF)
    * Hangul Syllables (U+AC00 – U+D7AF)
    * CJK Symbols and Punctuation (U+3000 – U+303F)
    * Fullwidth Forms (U+FF00 – U+FFEF)
    """
    cp = ord(character)
    return (
        0x4E00 <= cp <= 0x9FFF
        or 0x3400 <= cp <= 0x4DBF
        or 0x20000 <= cp <= 0x2A6DF
        or 0xF900 <= cp <= 0xFAFF
        or 0x3040 <= cp <= 0x309F
        or 0x30A0 <= cp <= 0x30FF
        or 0xAC00 <= cp <= 0xD7AF
        or 0x3000 <= cp <= 0x303F
        or 0xFF00 <= cp <= 0xFFEF
    )


# ------------------------------------------------------------------
# SheetsMDWriter — per-row Markdown generation (no LLM)
# ------------------------------------------------------------------

class SheetsMDWriter:
    """Generate per-row Markdown files for each Excel sheet.

    Creates three subdirectories under *base_dir* and writes one ``.md``
    file per row of each sheet.  Existing files are overwritten; files
    from previous runs that are no longer in the Excel data are left
    untouched (incremental overwrite strategy).
    """

    SUBDIR_PHENOMENON = "故障现象"
    SUBDIR_DIAGNOSTIC = "定界手段"
    SUBDIR_RECOVERY = "恢复方案"

    def __init__(self, base_dir: str | Path = "result") -> None:
        self._base_dir = Path(base_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write_all(
        self,
        phenomena: dict[str, FaultPhenomenon],
        diagnostics: dict[str, DiagnosticMethod],
        recoveries: dict[str, RecoveryPlan],
    ) -> dict[str, int]:
        """Generate Markdown files for all three sheet types.

        Returns a dict with counts, e.g.
        ``{"故障现象": 3, "定界手段": 4, "恢复方案": 5}``.
        """
        counts: dict[str, int] = {}
        counts[self.SUBDIR_PHENOMENON] = self._write_phenomena(phenomena)
        counts[self.SUBDIR_DIAGNOSTIC] = self._write_diagnostics(diagnostics)
        counts[self.SUBDIR_RECOVERY] = self._write_recoveries(recoveries)
        return counts

    # ------------------------------------------------------------------
    # Phenomenon
    # ------------------------------------------------------------------

    def _write_phenomena(self, phenomena: dict[str, FaultPhenomenon]) -> int:
        subdir = self._base_dir / self.SUBDIR_PHENOMENON
        subdir.mkdir(parents=True, exist_ok=True)
        for p in phenomena.values():
            filename = f"{p.fault_id}_{MDWriter.sanitize_filename(p.name)}.md"
            content = self._build_phenomenon_md(p)
            (subdir / filename).write_text(content, encoding="utf-8")
            logger.info("Wrote %s/%s (%d bytes)", self.SUBDIR_PHENOMENON, filename, len(content.encode("utf-8")))
        return len(phenomena)

    @staticmethod
    def _build_phenomenon_md(p: FaultPhenomenon) -> str:
        lines: list[str] = [f"# {p.fault_id}-{p.name}", ""]
        if p.description:
            lines += ["## 故障描述", "", p.description, ""]
        if p.category:
            lines.append(f"- **分类**：{p.category}")
        if p.perception_method:
            lines.append(f"- **故障感知手段**：{p.perception_method}")
        if p.has_perception:
            lines.append(f"- **是否已有感知手段**：{p.has_perception}")
        if p.diagnostic_ids:
            lines.append(f"- **关联定界手段**：{'、'.join(p.diagnostic_ids)}")
        lines.append("")  # trailing newline
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Diagnostic
    # ------------------------------------------------------------------

    def _write_diagnostics(self, diagnostics: dict[str, DiagnosticMethod]) -> int:
        subdir = self._base_dir / self.SUBDIR_DIAGNOSTIC
        subdir.mkdir(parents=True, exist_ok=True)
        for d in diagnostics.values():
            filename = f"{d.diagnostic_id}_{MDWriter.sanitize_filename(d.name)}.md"
            content = self._build_diagnostic_md(d)
            (subdir / filename).write_text(content, encoding="utf-8")
            logger.info("Wrote %s/%s (%d bytes)", self.SUBDIR_DIAGNOSTIC, filename, len(content.encode("utf-8")))
        return len(diagnostics)

    @staticmethod
    def _build_diagnostic_md(d: DiagnosticMethod) -> str:
        lines: list[str] = [f"# {d.diagnostic_id}-{d.name}", ""]
        if d.tool:
            lines.append(f"- **定界工具**：{d.tool}")
        if d.result:
            lines.append(f"- **定界结果**：{d.result}")
        if d.steps:
            lines.append("- **定界步骤**：")
            lines += _format_numbered_steps(d.steps)
        if d.recovery_ids:
            lines.append(f"- **关联恢复方案**：{'、'.join(d.recovery_ids)}")
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def _write_recoveries(self, recoveries: dict[str, RecoveryPlan]) -> int:
        subdir = self._base_dir / self.SUBDIR_RECOVERY
        subdir.mkdir(parents=True, exist_ok=True)
        for r in recoveries.values():
            filename = f"{r.recovery_id}_{MDWriter.sanitize_filename(r.name)}.md"
            content = self._build_recovery_md(r)
            (subdir / filename).write_text(content, encoding="utf-8")
            logger.info("Wrote %s/%s (%d bytes)", self.SUBDIR_RECOVERY, filename, len(content.encode("utf-8")))
        return len(recoveries)

    @staticmethod
    def _build_recovery_md(r: RecoveryPlan) -> str:
        lines: list[str] = [f"# {r.recovery_id}-{r.name}", ""]
        if r.tool:
            lines.append(f"- **恢复工具**：{r.tool}")
        if r.steps:
            lines.append("- **操作步骤**：")
            lines += _format_numbered_steps_list(r.steps)
        lines.append("")
        return "\n".join(lines)


def _strip_leading_number(text: str) -> str:
    """Remove a leading '1.', '1、', '1)' style number prefix from *text*."""
    return re.sub(r"^\s*\d+[.、)）]\s*", "", text)


def _format_numbered_steps(raw_steps: str) -> list[str]:
    """Parse a raw multi-line steps string into indented numbered list lines."""
    steps = [_strip_leading_number(s.strip()) for s in raw_steps.split("\n") if s.strip()]
    return [f"  {i+1}. {s}" for i, s in enumerate(steps)]


def _format_numbered_steps_list(steps: list[str]) -> list[str]:
    """Format a list of step strings into indented numbered list lines."""
    cleaned = [_strip_leading_number(s) for s in steps]
    return [f"  {i+1}. {s}" for i, s in enumerate(cleaned)]
