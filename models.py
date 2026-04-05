"""Domain data models for Excel to Markdown Wiki converter."""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Layer hierarchy constants
# ---------------------------------------------------------------------------

LAYER_ORDER = ["用户界面层", "接入层", "服务层", "平台层", "资源层"]


def get_layer_rank(layer: str) -> int:
    """Return rank for a layer — lower means higher level.

    服务层 and 平台层 share the same rank (2).
    """
    if layer in ("服务层", "平台层"):
        return 2
    return LAYER_ORDER.index(layer)


def is_higher_layer(layer_a: str, layer_b: str) -> bool | None:
    """Compare two layers.

    Returns True if *layer_a* is higher, False if *layer_b* is higher,
    or None if they are at the same level.
    """
    rank_a, rank_b = get_layer_rank(layer_a), get_layer_rank(layer_b)
    if rank_a == rank_b:
        return None
    return rank_a < rank_b


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


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
    layer: str = ""  # 故障表现层级


@dataclass
class SimilarityGroup:
    """A group of fault phenomena identified as similar by LLM analysis."""

    group_id: str
    phenomenon_ids: list[str]
    similarity_reason: str
    shared_symptoms: list[str]


@dataclass
class FaultCase:
    """Fully resolved fault case: phenomenon + diagnostics + recoveries."""

    phenomenon: FaultPhenomenon
    diagnostics: list[DiagnosticMethod] = field(default_factory=list)
    recoveries: list[RecoveryPlan] = field(default_factory=list)
    missing_ids: list[str] = field(default_factory=list)
    merged_diagnostics: list[dict] = field(default_factory=list)
    merged_recoveries: list[dict] = field(default_factory=list)

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

        result: dict = {
            "fault_id": self.phenomenon.fault_id,
            "phenomenon_name": self.phenomenon.name,
            "description": self.phenomenon.description,
            "layer": self.phenomenon.layer,
            "category": self.phenomenon.category,
            "perception_method": self.phenomenon.perception_method,
            "has_perception": self.phenomenon.has_perception,
            "diagnostics": diagnostics_data,
            "missing_ids": self.missing_ids,
        }

        if self.merged_diagnostics or self.merged_recoveries:
            result["merged_from_similar"] = {
                "diagnostics": self.merged_diagnostics,
                "recoveries": self.merged_recoveries,
            }

        return result
