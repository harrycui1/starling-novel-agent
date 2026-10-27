from app.checks import validate_direction
from app.config import settings
from app.llm.structured import structured
from app.schemas import Direction
from app.services import initial_bible
from app.pipeline.context import NodeResult


async def run(ctx):
    version = ctx.version
    bible = initial_bible(ctx.project_id)
    def validate(direction):
        validate_direction(direction, bible)
        if not direction.opening_moment.strip():
            raise ValueError("请写明从原文结尾哪个瞬间接起")
    direction = await structured("n3_manual", {"bible": bible.model_dump(), "manual_text": version.direction["manual_text"], "trope_vocab": settings.trope_vocab}, Direction, ctx.project_id, ctx.version_id, validate=validate)
    # Manual normalization is a separate human checkpoint before outline generation.
    from app.services import save
    version.direction = direction.model_dump()
    save(version)
    return NodeResult("awaiting_direction_confirmation", "N4")
