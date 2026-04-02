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

from models import FaultCase

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
