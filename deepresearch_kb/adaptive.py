"""Deterministic evidence sufficiency and adaptive route selection."""
from dataclasses import dataclass
from typing import Literal
from .models import Evidence
from .sufficiency import assess_requirements, grounded_judge_sufficient
Route = Literal["stop", "quick", "deep"]
@dataclass(frozen=True)
class Sufficiency:
    route: Route; reason: str; evidence_count: int; has_conflict: bool = False
    terminal_status: str | None = None
class EvidenceSufficiency:
    def __init__(self, minimum_evidence=1):
        if minimum_evidence < 1: raise ValueError("minimum_evidence must be positive")
        self.minimum_evidence = minimum_evidence
    def evaluate(self, evidence: list[Evidence], *, conflict=False, depth=0):
        if conflict: return Sufficiency("deep", "evidence conflict requires deeper research", len(evidence), True)
        if len(evidence) >= self.minimum_evidence: return Sufficiency("stop", "minimum evidence threshold met", len(evidence))
        return Sufficiency("quick" if depth == 0 else "deep", "no sufficient evidence; try quick" if depth == 0 else "quick evidence insufficient", len(evidence))
class AdaptiveResearchRouter:
    def __init__(self, *, quick_search, deep_research, sufficiency=None, requirements=None, judge=None, max_deep_calls=1):
        self.quick_search, self.deep_research = quick_search, deep_research; self.sufficiency = sufficiency or EvidenceSufficiency()
        self.requirements, self.judge = tuple(requirements or ()), judge
        if type(max_deep_calls) is not int or max_deep_calls < 0: raise ValueError("max_deep_calls must be non-negative")
        self.max_deep_calls = max_deep_calls
    def _evaluate(self, evidence, *, conflict=False, depth=0):
        if self.requirements:
            results = assess_requirements(self.requirements, evidence)
            if conflict: return Sufficiency("deep", "evidence conflict requires deeper research", len(evidence), True)
            if all(result.satisfied for result in results): return Sufficiency("stop", "all evidence requirements satisfied", len(evidence))
            return Sufficiency("quick" if depth == 0 else "deep", "required claims remain missing", len(evidence))
        return self.sufficiency.evaluate(evidence, conflict=conflict, depth=depth)
    async def run(self, query, *, internal, conflict=False):
        decisions=[self._evaluate(internal, conflict=conflict)]
        if conflict:
            if self.max_deep_calls < 1:
                return "deep", list(internal), [Sufficiency("deep", "conflict requires deep but deep budget is zero", len(internal), True, "unknown")]
            deep=await self.deep_research(query); combined=list(internal)+list(deep)
            decisions.append(Sufficiency("deep", "deep executed; conflict remains unresolved without reassessment", len(combined), True, "conflict"))
            return "deep", combined, decisions
        if decisions[0].route == "stop": return decisions[0].route, internal, decisions
        quick=await self.quick_search(query); combined=list(internal)+list(quick); decisions.append(self._evaluate(combined, depth=1))
        if self.judge is not None and self.requirements and decisions[-1].route == "deep":
            reviews = [await self.judge.judge(req, combined) for req in self.requirements]
            if all(grounded_judge_sufficient(req, combined, review)
                   for req, review in zip(self.requirements, reviews)):
                decisions[-1] = Sufficiency("stop", "semantic judge confirmed all requirements", len(combined))
                return "quick", combined, decisions
        if decisions[-1].route == "stop": return "quick", combined, decisions
        if self.max_deep_calls < 1:
            decisions.append(Sufficiency("deep", "quick evidence insufficient; deep budget exhausted", len(combined), False, "insufficient"))
            return "deep", combined, decisions
        deep=await self.deep_research(query)
        combined.extend(deep)
        final = self._evaluate(combined, depth=2)
        decisions.append(Sufficiency("deep", "deep completed; " + final.reason, len(combined),
                                     final.has_conflict, "sufficient" if final.route == "stop" else "insufficient"))
        return "deep", combined, decisions

    async def run_with_conflict_checker(self, query, *, internal, conflict_checker=None):
        conflict = False
        if conflict_checker is not None:
            review = await conflict_checker.check(internal)
            if review.get("status") in ("unknown", "not_evaluated"):
                deep = await self.deep_research(query)
                combined = list(internal) + list(deep)
                return "deep", combined, [Sufficiency("deep", "conflict assessment unknown; no sufficient verdict", len(combined), False, "unknown")]
            conflict = review.get("conflict_detected", False)
        return await self.run(query, internal=internal, conflict=conflict)
