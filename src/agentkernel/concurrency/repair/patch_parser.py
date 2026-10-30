import json

from pydantic import BaseModel, ConfigDict, Field

from .source_edits import EditError, SourceEdit, edits_to_diff


def validation_details(error: ValueError) -> list[dict[str, str]]:
    """Only schema locations/types, never echoed model text or secret-bearing values."""
    if isinstance(error, EditError):
        return [{"field": f"edits.{error.index}", "type": error.code, "hint": error.hint}]
    if hasattr(error, "errors"):
        return [{"field": ".".join(str(part) for part in item["loc"]), "type": item["type"]}
                for item in error.errors(include_input=False, include_context=False)[:10]]
    return [{"field": "patch", "type": "invalid_unified_diff_or_size"}]


class RepairDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    diagnosis: str = Field(min_length=1, max_length=8000)
    root_cause: str = Field(min_length=1, max_length=8000)
    confidence: float = Field(ge=0, le=1)
    reasoning_summary: str = Field(default="", max_length=8000)
    expected_effect: str = Field(max_length=8000)
    risk_notes: list[str] = Field(max_length=20)


class RepairProposal(RepairDetails):
    """Canonical report/application contract; the strict applier validates the diff."""
    patch: str = Field(min_length=1, max_length=262144)


class EditProposal(RepairDetails):
    """Preferred model response. The application supplies hunk offsets/counts."""
    edits: list[SourceEdit] = Field(min_length=1, max_length=32)


def parse_repair(text: str, sources: dict[str, str] | None = None) -> RepairProposal:
    if len(text) > 300000:
        raise ValueError("Repair response exceeds size limit")
    data = json.loads(text)
    if isinstance(data, dict) and "edits" in data:
        edits = EditProposal.model_validate_json(text)
        if sources is None:
            raise EditError("edit_sources_required", 0, "Trusted original source context is required for source edits.")
        return RepairProposal(**edits.model_dump(exclude={"edits"}), patch=edits_to_diff(edits.edits, sources))
    proposal = RepairProposal.model_validate_json(text)
    if not proposal.patch.startswith(("--- ", "diff --git ")):
        raise ValueError("The patch must contain only a unified diff")
    return proposal
