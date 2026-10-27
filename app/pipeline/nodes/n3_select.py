from app.checks import validate_direction
from app.llm.structured import structured
from app.schemas import Direction
from app.services import initial_bible
from app.pipeline.context import NodeResult


async def run(ctx):
    version = ctx.version
    bible = initial_bible(ctx.project_id)
    direction = await structured("n3_manual", {"bible": bible.model_dump(), "manual_text": version.direction["manual_text"]}, Direction, ctx.project_id, ctx.version_id, validate=lambda d: validate_direction(d, bible))
    # Manual normalization is a separate human checkpoint before outline generation.
    from app.services import save
    version.direction = direction.model_dump()
    save(version)
    return NodeResult("awaiting_direction_confirmation", "N4")
