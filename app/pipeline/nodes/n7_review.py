from app.checks import draft_issues
from app.llm.structured import structured
from app.models import ChapterReview
from app.schemas import ManuscriptReview
from app.services import rows, save, current_drafts, emit
from app.pipeline.context import NodeResult, manuscript_context
from app.pipeline.nodes.n6_write import chapters


async def run(ctx):
    drafts = current_drafts(ctx.version_id)
    # A saved review is the checkpoint, including a visible model-service error.
    draft_ids = [d.id for d in drafts]
    request = ctx.version.online_metrics.get("review_request", 0)
    reviewed = {r.draft_id for r in rows(ChapterReview, ChapterReview.draft_id.in_(draft_ids)) if r.llm_review.get("_draft_ids") == draft_ids and r.llm_review.get("_request", 0) == request}
    if drafts and all(d.id in reviewed for d in drafts):
        return NodeResult("awaiting_review", "N7")
    plans = {p.index: p for p in chapters(ctx)}
    rules = {d.index: draft_issues(d.content, plans[d.index]) for d in drafts}
    def validate(review):
        if sorted(c.index for c in review.chapters) != sorted(d.index for d in drafts):
            raise ValueError("审核须逐章返回当前续写的全部章号，不得遗漏或重复")
    try:
        result = await structured("n7_review", {"context": manuscript_context(ctx), "rule_issues": rules}, ManuscriptReview, ctx.project_id, ctx.version_id, validate=validate)
        feedback = {c.index: c.model_dump(exclude={"index"}) for c in result.chapters}
    except Exception as error:
        feedback = {d.index: {"error": str(error)[:2000], "fix_suggestions": []} for d in drafts}
        emit(ctx.project_id, ctx.version_id, "review_warning", message="审核未完成，正文已保存，可继续编辑或重新审核。")
    save(*(ChapterReview(draft_id=d.id, verdict=feedback[d.index].get("verdict", "unreviewed"), rule_issues=rules[d.index], llm_review={**feedback[d.index], "_draft_ids": draft_ids, "_request": request}) for d in drafts))
    return NodeResult("awaiting_review", "N7")
