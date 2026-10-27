from app.checks import clean_draft
from app.llm.gateway import gateway
from app.models import EditorAction
from app.schemas import Outline
from app.services import rows, save, store_draft, current_drafts, latest_outline, emit
from app.pipeline.context import NodeResult, build_write_context
from app.pipeline.nodes.n4_outline import allocate_words


def chapters(ctx):
    outline = Outline.model_validate(latest_outline(ctx.version_id).data)
    # Old confirmed outlines did not store chapter word targets.
    if not all(c.target_words for c in outline.chapters):
        allocate_words(outline, ctx.version.target_words)
    return outline.chapters


async def write_one(ctx, plan, existing=None, instruction=""):
    context = build_write_context(ctx, plan)
    if instruction:
        content = await gateway.complete("n6_rewrite_chapter", {"context": context, "draft": existing.content, "suggestions": [instruction]}, [], ctx.project_id, ctx.version_id)
    else:
        content = await gateway.complete("n6_write_chapter", {"context": context}, [], ctx.project_id, ctx.version_id)
    return store_draft(ctx.version_id, plan.index, plan.title, clean_draft(content, plan.index, plan.title))


async def run(ctx):
    for plan in chapters(ctx):
        draft = next((d for d in current_drafts(ctx.version_id) if d.index == plan.index), None)
        if draft is None:
            await write_one(ctx, plan)
        version = ctx.version
        version.current_chapter = plan.index
        save(version)
        emit(ctx.project_id, ctx.version_id, "chapter_completed", index=plan.index, completed=len([d for d in current_drafts(ctx.version_id) if d.index <= plan.index]), total=version.total_chapters)
    return NodeResult("reviewing", "N7")


async def edit(ctx):
    action = rows(EditorAction, EditorAction.version_id == ctx.version_id, EditorAction.action.in_(["chapter_edit", "chapter_regenerate"]), order=EditorAction.id.desc())[0]
    index = action.payload["index"]
    plan = next(p for p in chapters(ctx) if p.index == index)
    draft = next(d for d in current_drafts(ctx.version_id) if d.index == index)
    if action.action == "chapter_regenerate":
        if draft.id == action.payload["before_draft_id"]:
            draft = await write_one(ctx, plan, existing=draft, instruction=action.payload["instruction"])
        action.payload = {**action.payload, "generated_draft_id": draft.id}
        save(action)
    return NodeResult("reviewing", "N7")
