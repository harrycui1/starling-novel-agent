from app.llm.structured import structured
from app.schemas import Direction
from app.services import save
from app.pipeline.context import NodeResult, source_context


async def run(ctx):
    version = ctx.version
    if "manual_text" not in version.direction:
        return NodeResult("awaiting_direction_confirmation", "N4")
    direction = await structured("n3_manual", {"source_chapters": source_context(ctx), "manual_text": version.direction["manual_text"]}, Direction, ctx.project_id, ctx.version_id)
    version.direction = direction.model_dump()
    save(version)
    return NodeResult("awaiting_direction_confirmation", "N4")
