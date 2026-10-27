from uuid import uuid4

from app.llm.structured import structured
from app.models import DirectionCandidate
from app.schemas import Directions
from app.services import rows, save, source_understanding
from app.pipeline.context import NodeResult, source_context


async def run(ctx):
    previous = rows(DirectionCandidate, DirectionCandidate.project_id == ctx.project_id)
    summary = source_understanding(ctx.project_id)
    inputs = {"source_chapters": source_context(ctx), "understanding": summary.data if summary else None, "count": 3, "avoid": [{"title": d.data["title"], "main_trope": d.data["main_trope"]} for d in previous]}
    def validate(batch):
        if len(batch.directions) != 3:
            raise ValueError("请生成三个方向")
        tropes = {"".join(d.main_trope.split()).casefold() for d in batch.directions}
        if "" in tropes or len(tropes) != 3:
            raise ValueError("三个方向的主套路必须非空且互不重复")
    batch = await structured("n2_directions", inputs, Directions, ctx.project_id, validate=validate)
    batch_id = uuid4().hex
    candidates = [DirectionCandidate(project_id=ctx.project_id, batch_id=batch_id, data=d.model_dump(), shortlisted=True) for d in batch.directions]
    project = ctx.project
    project.active_batch = batch_id
    save(*candidates, project)
    return NodeResult("awaiting_direction", "N2")
