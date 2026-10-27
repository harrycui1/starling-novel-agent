import asyncio
import json
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from app.models import PipelineEvent, Project, Version
from app.services import rows, one

router = APIRouter()


@router.get("/events")
async def events(request: Request, project_id: int | None = None, version_id: int | None = None, after: int = 0, last_event_id: str | None = Header(None)):
    if version_id is not None:
        version = one(Version, version_id)
        if not version:
            raise HTTPException(404, "找不到续写版本")
        project_id = version.project_id
    if project_id is None or not one(Project, project_id):
        raise HTTPException(404, "请指定有效project_id或version_id")
    try:
        cursor = max(after, int(last_event_id or 0))
    except ValueError:
        raise HTTPException(422, "无效事件游标")
    async def stream():
        nonlocal cursor
        idle = 0
        while not await request.is_disconnected():
            cond = [PipelineEvent.id > cursor, PipelineEvent.project_id == project_id]
            if version_id is not None:
                cond.append(PipelineEvent.version_id == version_id)
            batch = rows(PipelineEvent, *cond, order=PipelineEvent.id)
            for event in batch:
                cursor = event.id
                yield f"id: {event.id}\nevent: progress\ndata: {json.dumps({'kind': event.kind, **event.data}, ensure_ascii=False)}\n\n"
            idle += 1
            if idle % 15 == 0:
                yield ": heartbeat\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
