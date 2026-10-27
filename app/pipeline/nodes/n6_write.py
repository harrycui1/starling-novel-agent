from app.checks import clean_draft, draft_issues, merge_verdict, normalize
from app.config import settings
from app.llm.gateway import gateway
from app.llm.structured import structured
from app.models import ChapterReview, StoryBibleSnapshot, EditorAction
from app.schemas import BiblePatch, ChapterPlan, ReviewResult, StoryBible, Digest
from app.services import rows, save, store_draft, current_drafts, latest_plans, emit, version_bible
from app.pipeline.context import NodeResult, build_write_context


def merge_patch(bible, patch, index, title):
    result = bible.model_copy(deep=True)
    warnings = []
    characters = {c.name: c for c in result.characters}
    for update in patch.character_updates:
        if update.name not in characters:
            warnings.append({"type": "unknown_character_update", "name": update.name})
            continue
        target = characters[update.name]
        if update.goal_now is not None:
            target.goal_now = update.goal_now
        target.status_now.update(update.status_now)
        target.addressing.update({name: value for name, value in update.addressing.items() if name in characters})
    relations = {(r.a, r.b): r for r in result.relations}
    for relation in patch.relation_updates:
        if relation.a in characters and relation.b in characters:
            relations[(relation.a, relation.b)] = relation
        else:
            warnings.append({"type": "unknown_relation_update", "a": relation.a, "b": relation.b})
    result.relations = list(relations.values())
    foreshadows = {f.id: f for f in result.foreshadows}
    for f in patch.foreshadow_updates:
        foreshadows[f.id] = f
    result.foreshadows = list(foreshadows.values())
    result.timeline.extend(event for event in patch.timeline_add if event.chapter == index)
    result.chapter_digests = [d for d in result.chapter_digests if d.chapter != index] + [Digest(chapter=index, title=title, digest=patch.chapter_digest)]
    return StoryBible.model_validate(result.model_dump()), warnings


async def update_state(ctx, bible, draft, lineage):
    patch = await structured("n6_bible_update", {"bible": bible.model_dump(), "chapter": draft.model_dump()}, BiblePatch, ctx.project_id, ctx.version_id)
    updated, warnings = merge_patch(bible, patch, draft.index, draft.title)
    save(StoryBibleSnapshot(project_id=ctx.project_id, version_id=ctx.version_id, after_chapter=draft.index, data=updated.model_dump(), warnings=[*warnings, {"type": "checkpoint", "draft_ids": lineage}]))
    return updated


async def ensure_state(ctx, before):
    start = ctx.sources[-1].index
    bible = version_bible(ctx.version_id, before=start + 1)
    snapshots = rows(StoryBibleSnapshot, StoryBibleSnapshot.version_id == ctx.version_id)
    lineage = []
    for draft in current_drafts(ctx.version_id):
        if draft.index >= before:
            break
        lineage.append(draft.id)
        valid = [s for s in snapshots if s.after_chapter == draft.index and any(w.get("type") == "checkpoint" and w.get("draft_ids") == lineage for w in s.warnings)]
        if valid:
            bible = StoryBible.model_validate(max(valid, key=lambda s: s.id).data)
        else:
            bible = await update_state(ctx, bible, draft, list(lineage))
    return bible


async def review_draft(ctx, draft, plan, bible, context):
    issues = draft_issues(draft.content, plan, bible)
    def validate_review(review):
        for issue in [*review.consistency_issues, *review.plan_deviation, *review.pacing_issues, *review.ai_flavor_issues]:
            if not normalize(issue.quote) or normalize(issue.quote) not in normalize(draft.content):
                raise ValueError("审核引文必须逐字来自当前正文，不得编造或改写引文")
    review = await structured("n6_review_chapter", {"context": context, "draft": draft.content, "rule_issues": issues}, ReviewResult, ctx.project_id, ctx.version_id, validate=validate_review)
    row = ChapterReview(draft_id=draft.id, verdict=merge_verdict(issues, review), rule_issues=issues, llm_review=review.model_dump())
    save(row)
    return row


async def write_one(ctx, plan, bible, existing=None, instruction="", author="ai"):
    context = build_write_context(ctx, plan, bible)
    draft = existing
    if instruction:
        content = await gateway.complete("n6_rewrite_chapter", {"context": context, "draft": existing.content, "issues": [], "suggestions": [instruction]}, [], ctx.project_id, ctx.version_id)
        draft = store_draft(ctx.version_id, plan.index, plan.title, clean_draft(content, plan.index, plan.title), author)
    elif draft is None:
        content = await gateway.complete("n6_write_chapter", {"context": context}, [], ctx.project_id, ctx.version_id)
        draft = store_draft(ctx.version_id, plan.index, plan.title, clean_draft(content, plan.index, plan.title))
    remaining_rewrites = max(0, settings.max_rewrite - (existing.rev if existing and not instruction else 0))
    for attempt in range(remaining_rewrites + 1):
        reviews = rows(ChapterReview, ChapterReview.draft_id == draft.id, order=ChapterReview.id.desc())
        review = reviews[0] if reviews else await review_draft(ctx, draft, plan, bible, context)
        if review.verdict in {"pass", "block"} or attempt == remaining_rewrites or author != "ai":
            break
        raw = await gateway.complete("n6_rewrite_chapter", {"context": context, "draft": draft.content, "issues": {"rules": review.rule_issues, "review": review.llm_review}, "suggestions": review.llm_review.get("fix_suggestions", [])}, [], ctx.project_id, ctx.version_id)
        draft = store_draft(ctx.version_id, plan.index, plan.title, clean_draft(raw, plan.index, plan.title))
    return draft


async def run(ctx):
    for row in latest_plans(ctx.version_id):
        plan = ChapterPlan.model_validate(row.data)
        drafts = {d.index: d for d in current_drafts(ctx.version_id)}
        draft = drafts.get(plan.index)
        lineage = [d.id for d in current_drafts(ctx.version_id) if d.index <= plan.index]
        snapshots = rows(StoryBibleSnapshot, StoryBibleSnapshot.version_id == ctx.version_id, StoryBibleSnapshot.after_chapter == plan.index)
        if draft and any(any(w.get("type") == "checkpoint" and w.get("draft_ids") == lineage for w in s.warnings) for s in snapshots):
            continue
        bible = await ensure_state(ctx, plan.index)
        if not draft or not any(r.verdict == "pass" for r in rows(ChapterReview, ChapterReview.draft_id == draft.id)):
            draft = await write_one(ctx, plan, bible, existing=draft)
        lineage = [d.id for d in current_drafts(ctx.version_id) if d.index <= plan.index]
        await update_state(ctx, bible, draft, lineage)
        version = ctx.version
        version.current_chapter = plan.index
        save(version)
        emit(ctx.project_id, ctx.version_id, "chapter_completed", index=plan.index, completed=len([d for d in current_drafts(ctx.version_id) if d.index <= plan.index]), total=version.total_chapters)
    return NodeResult("awaiting_review", "N6")


async def edit(ctx):
    actions = rows(EditorAction, EditorAction.version_id == ctx.version_id, EditorAction.action.in_(["chapter_edit", "chapter_regenerate"]), order=EditorAction.id.desc())
    action = actions[0]
    index = action.payload["index"]
    plan = next(ChapterPlan.model_validate(p.data) for p in latest_plans(ctx.version_id) if p.index == index)
    bible = await ensure_state(ctx, index)
    draft = next(d for d in current_drafts(ctx.version_id) if d.index == index)
    if action.action == "chapter_regenerate" and not action.payload.get("generated_draft_id"):
        draft = await write_one(ctx, plan, bible, existing=draft, instruction=action.payload["instruction"])
        action.payload = {**action.payload, "generated_draft_id": draft.id}
        save(action)
    else:
        context = build_write_context(ctx, plan, bible)
        if not rows(ChapterReview, ChapterReview.draft_id == draft.id):
            await review_draft(ctx, draft, plan, bible, context)
    await update_state(ctx, bible, draft, [d.id for d in current_drafts(ctx.version_id) if d.index <= index])
    return NodeResult("awaiting_review", "N6")
