from ..engine import ResearchEngine


class ResearchService:
    def __init__(self, engine: ResearchEngine):
        self.engine = engine

    async def run(self, query, *, knowledge_base_ids, output_dir):
        return await self.engine.run(query, knowledge_base_ids=knowledge_base_ids,
                                     requirements=None, output_dir=output_dir)
