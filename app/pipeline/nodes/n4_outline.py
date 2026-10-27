from app.checks import chapter_count, outline_issues, validate_new_characters
from app.config import settings
from app.llm.structured import structured
from app.models import OutlineRevision
from app.schemas import Outline, Direction
from app.services import initial_bible, save, latest_outline
from app.pipeline.context import NodeResult


async def run(ctx):
    bible, version = initial_bible(ctx.project_id), ctx.version
    count, start = chapter_count(version.target_words, ctx.project.channel), ctx.sources[-1].index + 1
    direction = Direction.model_validate(version.direction)
    def validate(outline):
        validate_new_characters(outline.new_characters, bible)
        if {c.name for c in direction.new_characters} - {c.name for c in outline.new_characters}:
            raise ValueError("大纲遗漏方向卡中声明的新增角色")
    issues, outline = [], None
    for _ in range(settings.structured_max_retry + 1):
        outline = await structured("n4_outline", {"bible": bible.model_dump(), "direction": version.direction, "start": start, "count": count, "target_words": version.target_words, "max_gap": settings.max_gap_between_payoffs, "issues": issues}, Outline, ctx.project_id, ctx.version_id, validate=validate)
        issues = outline_issues(outline, direction, start, count)
        # Cardinality is a hard structural invariant, not an editorial warning.
        if [c.index for c in outline.chapters] != list(range(start, start + count)):
            if _ == settings.structured_max_retry:
                raise ValueError("大纲章节数或章号错误")
            continue
        if not issues:
            break
    old = latest_outline(ctx.version_id)
    save(OutlineRevision(version_id=ctx.version_id, rev=old.rev + 1 if old else 1, data=outline.model_dump(), warnings=issues))
    version.total_chapters = count
    save(version)
    return NodeResult("awaiting_outline", "N5")
