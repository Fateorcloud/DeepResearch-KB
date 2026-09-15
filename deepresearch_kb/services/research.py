from ..engine import ResearchEngine
from ..sufficiency import EvidenceRequirement


class ResearchService:
    def __init__(self, engine: ResearchEngine):
        self.engine = engine

    async def run(self, query, *, knowledge_base_ids,
                  requirements: EvidenceRequirement, output_dir,
                  as_of=None, max_deep_calls=1, progress=None,
                  output_language=None, research_depth=None):
        if not isinstance(requirements, EvidenceRequirement):
            raise ValueError("requirements must be an EvidenceRequirement")
        options = dict(
            knowledge_base_ids=knowledge_base_ids, requirements=requirements,
            output_dir=output_dir, as_of=as_of, max_deep_calls=max_deep_calls)
        if progress is not None:
            options["progress"] = progress
        if output_language is not None:
            options["output_language"] = output_language
        if research_depth is not None:
            options["research_depth"] = research_depth
        return await self.engine.run(query, **options)
