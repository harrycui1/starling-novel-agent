from app.checks import validate_plans, allocate_scene_words
from app.llm.structured import structured
from app.models import ChapterPlanRow
from app.schemas import ChapterPlans, Outline
from app.services import version_bible, latest_outline, rows, save
from app.pipeline.context import NodeResult


async def run(ctx):
    bible, version = version_bible(ctx.version_id), ctx.version
    outline = Outline.model_validate(latest_outline(ctx.version_id).data)
    plans = []
    batch_size = 5 if len(outline.chapters) > 10 else len(outline.chapters)
    for start in range(0, len(outline.chapters), batch_size):
        batch = outline.chapters[start:start + batch_size]
        partial_outline = outline.model_copy(update={"chapters": batch})
        chapter_target = version.target_words // len(outline.chapters)
        def validate_batch(result):
            result.plans = [allocate_scene_words(plan) for plan in result.plans]
            validate_plans(result.plans, partial_outline, bible, chapter_target * len(batch))
        result = await structured("n5_chapter_plan", {"bible": bible.model_dump(), "outline": outline.model_dump(), "chapters": [c.model_dump() for c in batch], "previous_plans": [p.model_dump() for p in plans], "target_words": version.target_words, "chapter_target": chapter_target}, ChapterPlans, ctx.project_id, ctx.version_id, validate=validate_batch)
        plans.extend(result.plans)
    validate_plans(plans, outline, bible, version.target_words)
    previous = rows(ChapterPlanRow, ChapterPlanRow.version_id == ctx.version_id)
    generation = max((p.generation for p in previous), default=0) + 1
    save(*(ChapterPlanRow(version_id=ctx.version_id, index=p.index, generation=generation, data=p.model_dump()) for p in plans))
    return NodeResult("writing", "N6")
