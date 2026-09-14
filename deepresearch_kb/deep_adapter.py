"""Reuse upstream deep mode and return attributable scraped evidence, not a report as fact."""

from .research import _external_evidence


def default_deep_factory(query):
    from gpt_researcher import GPTResearcher
    return GPTResearcher(query=query, report_type="deep", report_source="web",
                         verbose=False, mcp_strategy="disabled")


class UpstreamDeepResearch:
    def __init__(self, researcher_factory=default_deep_factory):
        self.researcher_factory = researcher_factory

    async def search(self, query):
        researcher = self.researcher_factory(query)
        if researcher.report_type != "deep":
            raise ValueError("Deep Adapter requires report_type='deep'")
        await researcher.conduct_research()
        # Deep learnings/report text may be model-generated. Preserve the actual
        # source records as Evidence so later sufficiency checks can cite them.
        sources = researcher.get_research_sources()
        records = [{"url": s.get("url") or s.get("href"),
                    "raw_content": s.get("raw_content") or s.get("body") or s.get("content")}
                   for s in sources if isinstance(s, dict)]
        return _external_evidence(records)
