from app.llm.structured import structured
from app.models import SourceUnderstanding
from app.schemas import SourceSummary
from app.services import save, source_understanding
from app.pipeline.context import NodeResult, source_context


async def run(ctx):
    if source_understanding(ctx.project_id) is None:
        summary = await structured("n1_understand", {"source_chapters": source_context(ctx), "genre_tags": ctx.project.genre_tags}, SourceSummary, ctx.project_id)
        save(SourceUnderstanding(project_id=ctx.project_id, data=summary.model_dump()))
    return NodeResult("generating_directions", "N2")
