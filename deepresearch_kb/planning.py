"""Structured source planning for Phase 2, initially deterministic and reviewable."""

from dataclasses import dataclass
from typing import Literal
from .models import Evidence

SourcePolicy = Literal["internal", "external", "hybrid"]


@dataclass(frozen=True)
class PlannedQuestion:
    question: str
    source_policy: SourcePolicy
    rationale: str


@dataclass(frozen=True)
class ResearchPlan:
    query: str
    questions: tuple[PlannedQuestion, ...]


@dataclass(frozen=True)
class PlannedEvidence:
    question: str
    source_policy: SourcePolicy
    evidence: Evidence


class RuleBasedSourcePlanner:
    """Small baseline planner; rules are explicit so errors are attributable."""

    def plan(self, query: str, questions: list[str] | None = None) -> ResearchPlan:
        if not query.strip():
            raise ValueError("query must not be blank")
        items = questions or [query]
        planned = []
        for question in items:
            text = question.strip()
            if not text:
                continue
            lowered = text.casefold()
            # "current project" is an internal state; only temporal language
            # that implies the outside world activates the external branch.
            asks_current = any(word in lowered for word in ("latest", "today", "now", "recent"))
            asks_internal = any(word in lowered for word in ("our ", "internal", "project", "team", "constraint"))
            if asks_current and asks_internal:
                policy, rationale = "hybrid", "current external facts plus project/internal constraints"
            elif asks_internal:
                policy, rationale = "internal", "question names project-owned context"
            else:
                policy, rationale = "external", "no explicit project-owned context requirement"
            planned.append(PlannedQuestion(text, policy, rationale))
        if not planned:
            raise ValueError("at least one non-blank question is required")
        return ResearchPlan(query.strip(), tuple(planned))


def plan_from_upstream_subqueries(query: str, subqueries: list[str]) -> ResearchPlan:
    """Wrap sub-queries produced by upstream without reimplementing generation."""
    return RuleBasedSourcePlanner().plan(query, subqueries)
