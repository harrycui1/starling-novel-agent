from app.checks import clean_draft, draft_issues, merge_verdict, normalize
from app.config import settings
from app.llm.gateway import gateway
from app.llm.structured import structured
from app.models import ChapterReview, StoryBibleSnapshot, EditorAction
from app.schemas import BiblePatch, ChapterPlan, ReviewResult, StoryBible, Digest, StateInventory
from app.services import rows, save, store_draft, current_drafts, latest_plans, emit, version_bible
from app.pipeline.context import NodeResult, build_write_context, build_review_context


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
    props = {item.name: item for item in result.props}
    for item in patch.prop_updates:
        if item.holder and item.holder not in characters:
            warnings.append({"type": "unknown_prop_holder", "name": item.name, "holder": item.holder})
            continue
        item = item.model_copy(update={"updated_in": index})
        props[item.name] = item
    result.props = list(props.values())
    scenes = {item.name: item for item in result.scene_states}
    for item in patch.scene_updates:
        if set(item.characters) - set(characters):
            warnings.append({"type": "unknown_scene_character", "name": item.name})
            continue
        scenes[item.name] = item.model_copy(update={"updated_in": index})
    result.scene_states = list(scenes.values())
    result.state_inventory_complete = True
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
    if not bible.state_inventory_complete:
        inventory = await structured("n1_state_inventory", {"chapters": [{"index": c.index, "title": c.title, "content": c.content} for c in ctx.sources], "characters": [c.name for c in bible.characters]}, StateInventory, ctx.project_id, ctx.version_id)
        bible.props, bible.scene_states = inventory.props, inventory.scene_states
        bible.state_inventory_complete = True
        for state in [*bible.props, *bible.scene_states]:
            state.updated_in = start
        save(StoryBibleSnapshot(project_id=ctx.project_id, version_id=ctx.version_id, after_chapter=start, data=bible.model_dump(), warnings=[{"type": "legacy_state_inventory"}]))
    snapshots = rows(StoryBibleSnapshot, StoryBibleSnapshot.version_id == ctx.version_id)
    lineage = []
    for draft in current_drafts(ctx.version_id):
        if draft.index >= before:
            break
        lineage.append(draft.id)
        valid = [s for s in snapshots if s.after_chapter == draft.index and s.data.get("state_inventory_complete") and any(w.get("type") == "checkpoint" and w.get("draft_ids") == lineage for w in s.warnings)]
        if valid:
            bible = StoryBible.model_validate(max(valid, key=lambda s: s.id).data)
        else:
            bible = await update_state(ctx, bible, draft, list(lineage))
    return bible


REVIEW_POLICY = "2026-10-27.2"


def filter_review_quotes(review, content):
    result = review.model_copy(deep=True)
    discarded = 0
    for key in ("consistency_issues", "plan_deviation", "pacing_issues", "ai_flavor_issues"):
        valid = [issue for issue in getattr(result, key) if normalize(issue.quote) and normalize(issue.quote) in normalize(content)]
        discarded += len(getattr(result, key)) - len(valid)
        setattr(result, key, valid)
    warnings = [{"code": "review_quote", "detail": f"已丢弃{discarded}条无法在当前正文核对的审核引文，其余意见保留。", "verdict": "info"}] if discarded else []
    return result, warnings


def persist_review(ctx, draft, plan, bible, review):
    review, warnings = filter_review_quotes(review, draft.content)
    issues = draft_issues(draft.content, plan, bible) + warnings
    row = ChapterReview(draft_id=draft.id, verdict=merge_verdict(issues, review), rule_issues=issues, llm_review={**review.model_dump(), "_policy": REVIEW_POLICY})
    save(row)
    return row


def current_review(ctx, draft, plan, bible):
    reviews = rows(ChapterReview, ChapterReview.draft_id == draft.id, order=ChapterReview.id.desc())
    if not reviews:
        return None
    latest = reviews[0]
    if latest.llm_review.get("_policy") != REVIEW_POLICY:
        # The old prompt classified repairable conflicts as block. Re-review
        # those drafts under the new policy instead of preserving that gate.
        if latest.llm_review.get("verdict") == "block":
            return None
        original = {key: value for key, value in latest.llm_review.items() if key in ReviewResult.model_fields}
        return persist_review(ctx, draft, plan, bible, ReviewResult.model_validate(original))
    return latest


async def review_draft(ctx, draft, plan, bible, context):
    issues = draft_issues(draft.content, plan, bible)
    review = await structured("n6_review_chapter", {"context": build_review_context(ctx, plan, bible), "draft": draft.content, "rule_issues": [i for i in issues if i["verdict"] != "info"]}, ReviewResult, ctx.project_id, ctx.version_id)
    return persist_review(ctx, draft, plan, bible, review)


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
        review = current_review(ctx, draft, plan, bible) or await review_draft(ctx, draft, plan, bible, context)
        if review.verdict in {"pass", "block"} or attempt == remaining_rewrites or author != "ai":
            break
        raw = await gateway.complete("n6_rewrite_chapter", {"context": context, "draft": draft.content, "issues": {"rules": [i for i in review.rule_issues if i["verdict"] != "info"], "review": {k: v for k, v in review.llm_review.items() if k != "_policy"}}, "suggestions": review.llm_review.get("fix_suggestions", [])}, [], ctx.project_id, ctx.version_id)
        draft = store_draft(ctx.version_id, plan.index, plan.title, clean_draft(raw, plan.index, plan.title))
    return draft


async def run(ctx):
    for row in latest_plans(ctx.version_id):
        plan = ChapterPlan.model_validate(row.data)
        drafts = {d.index: d for d in current_drafts(ctx.version_id)}
        draft = drafts.get(plan.index)
        lineage = [d.id for d in current_drafts(ctx.version_id) if d.index <= plan.index]
        snapshots = rows(StoryBibleSnapshot, StoryBibleSnapshot.version_id == ctx.version_id, StoryBibleSnapshot.after_chapter == plan.index)
        checkpoint = draft and any(s.data.get("state_inventory_complete") and any(w.get("type") == "checkpoint" and w.get("draft_ids") == lineage for w in s.warnings) for s in snapshots)
        previous_reviews = rows(ChapterReview, ChapterReview.draft_id == draft.id, order=ChapterReview.id.desc()) if draft else []
        if checkpoint and previous_reviews and previous_reviews[0].llm_review.get("_policy") == REVIEW_POLICY:
            continue
        bible = await ensure_state(ctx, plan.index)
        review = current_review(ctx, draft, plan, bible) if draft else None
        if not review or review.verdict not in {"pass", "block"}:
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
