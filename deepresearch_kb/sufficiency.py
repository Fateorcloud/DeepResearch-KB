"""Requirement-based evidence sufficiency; deterministic first, judge optional."""
from dataclasses import dataclass
from typing import Literal
from .models import Evidence

@dataclass(frozen=True)
class EvidenceRequirement:
    id: str
    required_claims: tuple[str, ...]
    required_source_types: tuple[str, ...] = ()
    minimum_distinct_sources: int = 1
    require_current_version: bool = False

@dataclass(frozen=True)
class RequirementResult:
    requirement_id: str
    satisfied: bool
    matched_evidence_ids: tuple[str, ...]
    missing_claims: tuple[str, ...]
    reason: str

def extract_claims(evidence: list[Evidence]) -> list[dict]:
    """Expose evidence as auditable claims without pretending to infer semantics."""
    claims = []
    for item in evidence:
        for ordinal, text in enumerate(filter(None, (part.strip() for part in item.text.replace("\n", ".").split(".")))):
            claims.append({"claim_id": f"{item.chunk_id}:{ordinal}", "evidence_id": item.chunk_id, "text": text,
             "source_type": item.source_type,
             "source_uri": item.source_uri, "version": item.version, "status": item.status,
             "effective_at": item.effective_at})
    return claims

class SufficiencyJudge:
    """Optional semantic fallback; malformed output remains unknown."""
    def __init__(self, reviewer): self.reviewer = reviewer
    async def judge(self, requirement, evidence):
        import json
        prompt = ("Assess whether the evidence satisfies the requirement. Return JSON only: "
            '{"status":"sufficient|insufficient|unknown","matched_claim_ids":[],"missing_claims":[],"reason":"..."}. '
            "Do not infer facts absent from evidence; preserve uncertainty.\n" +
            json.dumps({"requirement": requirement.__dict__, "claims": extract_claims(evidence)}, ensure_ascii=False))
        try:
            result = json.loads(await self.reviewer(prompt))
            if result.get("status") not in ("sufficient", "insufficient", "unknown"):
                raise ValueError("invalid status")
            if not isinstance(result.get("matched_claim_ids"), list) or not isinstance(result.get("missing_claims"), list) or not result.get("reason"):
                raise ValueError("invalid judge shape")
            valid = {c["claim_id"] for c in extract_claims(evidence)}
            if not set(result["matched_claim_ids"]) <= valid:
                raise ValueError("ungrounded claim id")
            return result
        except Exception as exc:
            return {"status": "unknown", "matched_claim_ids": [], "missing_claims": [], "reason": type(exc).__name__}

def assess_requirements(requirements: list[EvidenceRequirement], evidence: list[Evidence]):
    results = []
    for requirement in requirements:
        matches = [item for item in evidence if any(claim.casefold() in item.text.casefold() for claim in requirement.required_claims)]
        missing = tuple(claim for claim in requirement.required_claims if not any(claim.casefold() in item.text.casefold() for item in evidence))
        source_types = {item.source_type for item in matches}
        distinct_sources = {item.source_uri for item in matches}
        current_ok = not requirement.require_current_version or all(
            item.source_type == "external_web" or item.status == "active" for item in matches)
        satisfied = bool(matches) and not missing and set(requirement.required_source_types) <= source_types and len(distinct_sources) >= requirement.minimum_distinct_sources and current_ok
        results.append(RequirementResult(requirement.id, satisfied, tuple(item.chunk_id for item in matches), missing,
            "all claims/source/version requirements met" if satisfied else "missing claim, source type, distinct source, or current-version requirement"))
    return results
