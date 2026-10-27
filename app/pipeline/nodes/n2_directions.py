from collections import Counter
from datetime import timedelta
from uuid import uuid4
from random import SystemRandom

from app.checks import similarity, validate_direction
from app.config import settings
from app.llm.structured import structured
from app.models import DirectionCandidate, Version, now
from app.schemas import Directions, DirectionJudgments
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
            if not direction.opening_moment.strip():
                raise ValueError("每个方向都必须说明从原文结尾哪个具体瞬间接起")
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
    entries = [{"candidate_id": f"D{i + 1}", "direction": direction.model_dump()} for i, direction in enumerate(kept)]
    SystemRandom().shuffle(entries)
    expected = {entry["candidate_id"] for entry in entries}
    def validate_judgments(result):
        ids = [item.candidate_id for item in result.judgments]
        if len(ids) != len(expected) or set(ids) != expected:
            raise ValueError("必须为每个候选ID各输出一份评分，不得缺失、重复或错配")
        for item in result.judgments:
            if any(not getattr(item.judgment, key).reason.strip() for key in settings.judge_weights):
                raise ValueError("每个方向、每个评分维度都必须保留具体理由")
    judged = await structured("n3_judge", {"bible": bible.model_dump(), "candidates": entries, "channel": ctx.project.channel, "target_words": settings.target_words}, DirectionJudgments, ctx.project_id, validate=validate_judgments)
    judgments = {item.candidate_id: item.judgment for item in judged.judgments}
    positions = {item["candidate_id"]: i + 1 for i, item in enumerate(entries)}
    for i, direction in enumerate(kept):
        reference = f"D{i + 1}"
        judgment = judgments[reference]
        score = sum(getattr(judgment, key).score * weight for key, weight in settings.judge_weights.items())
        score -= tropes[direction.main_trope] / max(sum(tropes.values()), 1) * .5
        scores = {**judgment.model_dump(), "_meta": {"candidate_ref": reference, "presentation_position": positions[reference]}}
        candidates.append(DirectionCandidate(project_id=ctx.project_id, batch_id=batch_id, data=direction.model_dump(), judge_scores=scores, score=score))
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
