from app.checks import chapter_count
from app.llm.structured import structured
from app.models import OutlineRevision
from app.schemas import Outline
from app.services import save, latest_outline
from app.pipeline.context import NodeResult, source_context


def allocate_words(outline, target):
    base, extra = divmod(target, len(outline.chapters))
    for i, chapter in enumerate(outline.chapters):
        chapter.target_words = base + (i < extra)
    return outline


async def run(ctx):
    version = ctx.version
    old = latest_outline(ctx.version_id)
    if old:
        version.total_chapters = len(old.data["chapters"])
        save(version)
        return NodeResult("awaiting_outline", "N6")
    count, start = chapter_count(version.target_words, ctx.project.channel), ctx.sources[-1].index + 1
    def validate(outline):
        if [c.index for c in outline.chapters] != list(range(start, start + count)):
            raise ValueError("大纲章节数或章号错误")
    outline = await structured("n4_outline", {"source_chapters": source_context(ctx), "direction": version.direction, "start": start, "count": count, "target_words": version.target_words}, Outline, ctx.project_id, ctx.version_id, validate=validate)
    allocate_words(outline, version.target_words)
    version.total_chapters = count
    save(OutlineRevision(version_id=ctx.version_id, rev=1, data=outline.model_dump()), version)
    return NodeResult("awaiting_outline", "N6")
