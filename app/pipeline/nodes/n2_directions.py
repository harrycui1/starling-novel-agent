from collections import Counter
from datetime import timedelta
from uuid import uuid4

from app.checks import similarity, validate_direction
from app.config import settings
from app.llm.structured import structured
from app.models import DirectionCandidate, Version, now
from app.schemas import Directions, JudgeResult
from app.services import initial_bible, rows, save
from app.pipeline.context import NodeResult


async def run(ctx):
    bible = initial_bible(ctx.project_id)
    previous = rows(DirectionCandidate, DirectionCandidate.project_id == ctx.project_id)
    inputs = {"bible": bible.model_dump(), "count": settings.n2_candidates, "trope_vocab": settings.trope_vocab, "avoid": [{"title": d.data["title"], "main_trope": d.data["main_trope"]} for d in previous], "channel": ctx.project.channel}
    def validate(batch):
        if len(batch.directions) != settings.n2_candidates:
            raise ValueError("方向数量不符合要求")
        for direction in batch.directions:
            validate_direction(direction, bible)
        if len({d.main_trope for d in batch.directions}) < settings.n2_shortlist:
            raise ValueError("不同主套路数量不足")
    batch = await structured("n2_directions", inputs, Directions, ctx.project_id, validate=validate)
    kept = []
    for direction in batch.directions:
        if not any(direction.main_trope == old.main_trope and similarity(direction.synopsis, old.synopsis) > settings.n2_dedup_threshold for old in kept):
            kept.append(direction)
    recent = rows(Version, Version.created_at >= now() - timedelta(days=settings.n2_recent_window_days))
    from app.models import Project
    projects = {p.id: p for p in rows(Project)}
    tropes = Counter(v.direction.get("main_trope") for v in recent if set(ctx.project.genre_tags) & set(projects[v.project_id].genre_tags))
    candidates, batch_id = [], uuid4().hex
    for direction in kept:
        judgment = await structured("n3_judge", {"bible": bible.model_dump(), "direction": direction.model_dump(), "channel": ctx.project.channel, "target_words": settings.target_words}, JudgeResult, ctx.project_id)
        score = sum(getattr(judgment, k).score * weight for k, weight in settings.judge_weights.items())
        score -= tropes[direction.main_trope] / max(sum(tropes.values()), 1) * .5
        candidates.append(DirectionCandidate(project_id=ctx.project_id, batch_id=batch_id, data=direction.model_dump(), judge_scores=judgment.model_dump(), score=score))
    seen = set()
    for candidate in sorted(candidates, key=lambda c: c.score, reverse=True):
        trope = candidate.data["main_trope"]
        if trope not in seen and len(seen) < settings.n2_shortlist:
            candidate.shortlisted = True
            seen.add(trope)
    if len(seen) != settings.n2_shortlist:
        raise ValueError("去重后差异化方向不足，请重试")
    project = ctx.project
    project.active_batch = batch_id
    save(*candidates, project)
    return NodeResult("awaiting_direction", "N2")
