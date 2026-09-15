from ..engine import ResearchEngine
from ..sufficiency import EvidenceRequirement


class ResearchService:
    def __init__(self, engine: ResearchEngine):
        self.engine = engine

    async def run(self, query, *, knowledge_base_ids,
                  requirements: EvidenceRequirement, output_dir,
                  as_of=None, max_deep_calls=1):
        if not isinstance(requirements, EvidenceRequirement):
            raise ValueError("requirements must be an EvidenceRequirement")
        return await self.engine.run(query, knowledge_base_ids=knowledge_base_ids,
                                     requirements=requirements, output_dir=output_dir,
                                     as_of=as_of, max_deep_calls=max_deep_calls)
