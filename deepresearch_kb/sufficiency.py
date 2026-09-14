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

    def __post_init__(self):
        if not self.id.strip() or not self.required_claims or any(not c.strip() for c in self.required_claims):
            raise ValueError("requirement identity and non-empty claims required")
        if type(self.minimum_distinct_sources) is not int or self.minimum_distinct_sources < 1:
            raise ValueError("minimum_distinct_sources must be a positive integer")


def hard_constraints_met(requirement, evidence):
    """Semantic reviewers cannot waive provenance, source diversity or currency."""
    return (bool(evidence)
            and all(e.text.strip() and e.source_uri.strip() for e in evidence)
            and set(requirement.required_source_types) <= {e.source_type for e in evidence}
            and len({e.source_uri for e in evidence}) >= requirement.minimum_distinct_sources
            and (not requirement.require_current_version or all(
                e.source_type == "external_web" or e.status == "active" for e in evidence)))


def grounded_judge_sufficient(requirement, evidence, review):
    if review.get("status") != "sufficient" or review.get("missing_claims") != []:
        return False
    ids = review.get("matched_claim_ids")
    if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids):
        return False
    claims = {c["claim_id"]: c for c in extract_claims(evidence)}
    if not set(ids) <= claims.keys():
        return False
    evidence_ids = {claims[i]["evidence_id"] for i in ids}
    return hard_constraints_met(requirement, [e for e in evidence if e.chunk_id in evidence_ids])

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
            if result["status"] == "sufficient" and not grounded_judge_sufficient(requirement, evidence, result):
                raise ValueError("sufficient verdict violates hard constraints")
            return result
        except Exception as exc:
            return {"status": "unknown", "matched_claim_ids": [], "missing_claims": [], "reason": type(exc).__name__}

def configured_sufficiency_judge(usage=None):
    """Construct the optional judge through upstream's configured LLM provider."""
    from gpt_researcher.config import Config
    from gpt_researcher.llm_provider import GenericLLMProvider
    cfg = Config(); options = dict(cfg.llm_kwargs)
    options.update(model=cfg.smart_llm_model, temperature=0, max_tokens=1800, timeout=60, max_retries=0)
    if usage is not None: options["callbacks"] = [usage]
    provider = GenericLLMProvider.from_provider(cfg.smart_llm_provider, **options)
    async def reviewer(prompt):
        return await provider.get_chat_response([{"role":"user","content":prompt}], stream=False)
    return SufficiencyJudge(reviewer)

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
