"""Deterministic evidence sufficiency and adaptive route selection."""
from dataclasses import dataclass
from typing import Literal
from .models import Evidence
Route = Literal["stop", "quick", "deep"]
@dataclass(frozen=True)
class Sufficiency:
    route: Route; reason: str; evidence_count: int; has_conflict: bool = False
class EvidenceSufficiency:
    def __init__(self, minimum_evidence=1):
        if minimum_evidence < 1: raise ValueError("minimum_evidence must be positive")
        self.minimum_evidence = minimum_evidence
    def evaluate(self, evidence: list[Evidence], *, conflict=False, depth=0):
        if conflict: return Sufficiency("deep", "evidence conflict requires deeper research", len(evidence), True)
        if len(evidence) >= self.minimum_evidence: return Sufficiency("stop", "minimum evidence threshold met", len(evidence))
        return Sufficiency("quick" if depth == 0 else "deep", "no sufficient evidence; try quick" if depth == 0 else "quick evidence insufficient", len(evidence))
class AdaptiveResearchRouter:
    def __init__(self, *, quick_search, deep_research, sufficiency=None):
        self.quick_search, self.deep_research = quick_search, deep_research; self.sufficiency = sufficiency or EvidenceSufficiency()
    async def run(self, query, *, internal, conflict=False):
        decisions=[self.sufficiency.evaluate(internal, conflict=conflict)]
        if conflict:
            deep=await self.deep_research(query); combined=list(internal)+list(deep)
            decisions.append(Sufficiency("deep", "conflict escalated directly to deep research", len(combined), True))
            return "deep", combined, decisions
        if decisions[0].route == "stop": return decisions[0].route, internal, decisions
        quick=await self.quick_search(query); combined=list(internal)+list(quick); decisions.append(self.sufficiency.evaluate(combined, depth=1))
        if decisions[-1].route == "stop": return "quick", combined, decisions
        deep=await self.deep_research(query); combined.extend(deep); decisions.append(Sufficiency("deep", "deep research executed", len(combined), conflict)); return "deep", combined, decisions

    async def run_with_conflict_checker(self, query, *, internal, conflict_checker=None):
        conflict = False
        if conflict_checker is not None:
            conflict = (await conflict_checker.check(internal)).get("conflict_detected", False)
        return await self.run(query, internal=internal, conflict=conflict)
