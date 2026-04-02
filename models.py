"""Domain data models for Excel to Markdown Wiki converter."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RecoveryStep:
    """A single step in a recovery plan."""
    step_number: int
    action: str
    command: str | None = None
    is_dangerous: bool = False


@dataclass
class RecoveryPlan:
    """A recovery/quick-recovery plan from Sheet 3."""
    recovery_id: str  # QRxxxx or Rxxxx
    name: str
    steps: list[str] = field(default_factory=list)
    raw_steps: str = ""  # original text from Excel
    tool: str = ""


@dataclass
class DiagnosticMethod:
    """A diagnostic method from Sheet 2."""
    diagnostic_id: str  # Axxxx
    name: str
    steps: str = ""
    recovery_ids: list[str] = field(default_factory=list)
    tool: str = ""
    result: str = ""


@dataclass
class FaultPhenomenon:
    """A fault phenomenon from Sheet 1."""
    fault_id: str  # UPxxx or APxxx
    name: str
    description: str = ""
    diagnostic_ids: list[str] = field(default_factory=list)
    category: str = ""
    perception_method: str = ""
    has_perception: str = ""


@dataclass
class FaultCase:
    """Fully resolved fault case: phenomenon + diagnostics + recoveries."""
    phenomenon: FaultPhenomenon
    diagnostics: list[DiagnosticMethod] = field(default_factory=list)
    recoveries: list[RecoveryPlan] = field(default_factory=list)
    missing_ids: list[str] = field(default_factory=list)

    @property
    def has_missing_data(self) -> bool:
        return len(self.missing_ids) > 0

    @property
    def needs_llm_suggestions(self) -> bool:
        return len(self.diagnostics) == 0 or len(self.recoveries) == 0 or self.has_missing_data

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict for LLM prompt."""
        diagnostics_data = []
        for d in self.diagnostics:
            recoveries_data = []
            for rid in d.recovery_ids:
                matched = [r for r in self.recoveries if r.recovery_id == rid]
                if matched:
                    r = matched[0]
                    recoveries_data.append({
                        "recovery_id": r.recovery_id,
                        "name": r.name,
                        "steps": r.steps,
                        "tool": r.tool,
                    })
                else:
                    recoveries_data.append(f"[缺失关联数据：ID {rid}]")
            diagnostics_data.append({
                "diagnostic_id": d.diagnostic_id,
                "name": d.name,
                "steps": d.steps,
                "tool": d.tool,
                "result": d.result,
                "recoveries": recoveries_data,
            })
        return {
            "fault_id": self.phenomenon.fault_id,
            "phenomenon_name": self.phenomenon.name,
            "description": self.phenomenon.description,
            "category": self.phenomenon.category,
            "perception_method": self.phenomenon.perception_method,
            "has_perception": self.phenomenon.has_perception,
            "diagnostics": diagnostics_data,
            "missing_ids": self.missing_ids,
        }
