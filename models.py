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
    plan_type: str  # "quick_recovery" or "recovery"
    steps: list[str] = field(default_factory=list)
    raw_steps: str = ""  # original text from Excel


@dataclass
class DiagnosticMethod:
    """A diagnostic method from Sheet 2."""
    diagnostic_id: str  # Axxxx
    name: str
    description: str = ""
    steps: str = ""
    recovery_ids: list[str] = field(default_factory=list)


@dataclass
class FaultPhenomenon:
    """A fault phenomenon from Sheet 1."""
    fault_id: str  # UPxxx or APxxx
    name: str
    description: str = ""
    diagnostic_ids: list[str] = field(default_factory=list)


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
                        "type": r.plan_type,
                        "steps": r.steps,
                    })
                else:
                    recoveries_data.append(f"[缺失关联数据：ID {rid}]")
            diagnostics_data.append({
                "diagnostic_id": d.diagnostic_id,
                "name": d.name,
                "description": d.description,
                "steps": d.steps,
                "recoveries": recoveries_data,
            })
        return {
            "fault_id": self.phenomenon.fault_id,
            "phenomenon_name": self.phenomenon.name,
            "description": self.phenomenon.description,
            "diagnostics": diagnostics_data,
            "missing_ids": self.missing_ids,
        }
