import io
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlmodel import Session, select
from docx import Document

from app.db import get_session
from app.models import ChapterDraft, ChapterReview, EditorAction, LLMCall, OutlineRevision, Project, SourceChapter, Version
from app.schemas import ActionInput, EditOutline, EditChapter, Instruction, Outline
from app.checks import chapter_count, clean_draft, count_words
from app.services import rows, latest_outline, latest_plans, current_drafts, log_action
from app.pipeline.runner import runner
from app.pipeline.nodes.n4_outline import allocate_words

router = APIRouter()


def require_version(ident, session):
    version = session.get(Version, ident)
    if not version:
        raise HTTPException(404, "找不到续写版本")
    return version


def editable(version, statuses):
    if runner.busy(version.project_id, version.id) or version.status not in statuses:
        raise HTTPException(409, "当前阶段不能执行该操作")


@router.get("/versions/{ident}")
def detail(ident: int, session: Session = Depends(get_session)):
    version = require_version(ident, session)
    outline = latest_outline(ident)
    if outline and any(not c.get("target_words") for c in outline.data["chapters"]):
        outline.data = allocate_words(Outline.model_validate(outline.data), version.target_words).model_dump()
    history = rows(ChapterDraft, ChapterDraft.version_id == ident, order=ChapterDraft.index)
    ids = [d.id for d in history]
    return {"version": version, "outline": outline, "outline_history": rows(OutlineRevision, OutlineRevision.version_id == ident, order=OutlineRevision.rev), "plans": latest_plans(ident), "chapters": current_drafts(ident), "draft_history": history, "reviews": rows(ChapterReview, ChapterReview.draft_id.in_(ids)), "actions": rows(EditorAction, EditorAction.version_id == ident, order=EditorAction.id), "calls": rows(LLMCall, LLMCall.version_id == ident, order=LLMCall.id)}


@router.post("/versions/{ident}/direction/confirm", status_code=202)
async def confirm_direction(ident: int, body: ActionInput, session: Session = Depends(get_session)):
    version = require_version(ident, session)
    editable(version, {"awaiting_direction_confirmation"})
    version.status, version.current_node = "queued", "N4"
    session.add(version)
    log_action(session, version.project_id, ident, "direction_confirm", body.editor, direction=version.direction)
    session.commit()
    runner.enqueue(version.project_id, ident)
    return {"status": "queued"}


@router.put("/versions/{ident}/outline")
def edit_outline(ident: int, body: EditOutline, session: Session = Depends(get_session)):
    version = require_version(ident, session)
    editable(version, {"awaiting_outline"})
    project = session.get(Project, version.project_id)
    sources = rows(SourceChapter, SourceChapter.project_id == project.id, order=SourceChapter.index)
    count = chapter_count(version.target_words, project.channel)
    if [c.index for c in body.outline.chapters] != list(range(sources[-1].index + 1, sources[-1].index + count + 1)):
        raise HTTPException(422, "请保持指定章节数与连续章号")
    if any(not c.target_words for c in body.outline.chapters) or sum(c.target_words for c in body.outline.chapters) != version.target_words:
        raise HTTPException(422, "各章目标字数须为正数，合计须等于版本目标字数")
    old = latest_outline(ident)
    revision = OutlineRevision(version_id=ident, rev=old.rev + 1, data=body.outline.model_dump(), author=body.editor)
    session.add(revision)
    log_action(session, project.id, ident, "outline_edit", body.editor, before=old.data, after=revision.data)
    session.commit()
    session.refresh(revision)
    return revision


@router.post("/versions/{ident}/outline/confirm", status_code=202)
async def confirm_outline(ident: int, body: ActionInput, session: Session = Depends(get_session)):
    version = require_version(ident, session)
    editable(version, {"awaiting_outline"})
    outline = latest_outline(ident)
    outline.confirmed = True
    version.status, version.current_node = "queued", "N6"
    session.add_all([outline, version])
    log_action(session, version.project_id, ident, "outline_confirm", body.editor, revision=outline.rev, warnings=outline.warnings, new_characters=outline.data["new_characters"])
    session.commit()
    runner.enqueue(version.project_id, ident)
    return {"status": "queued"}


def find_draft(ident, index):
    draft = next((d for d in current_drafts(ident) if d.index == index), None)
    if not draft:
        raise HTTPException(404, "找不到该章节")
    return draft


def mark_edit(version, index, session):
    version.stale_chapters = sorted(set(version.stale_chapters) | {d.index for d in current_drafts(version.id) if d.index > index})
    version.status, version.current_node = "queued", "N6_EDIT"
    session.add(version)


@router.put("/versions/{ident}/chapters/{index}")
async def edit_chapter(ident: int, index: int, body: EditChapter, session: Session = Depends(get_session)):
    version = require_version(ident, session)
    editable(version, {"awaiting_review"})
    old = find_draft(ident, index)
    all_drafts = rows(ChapterDraft, ChapterDraft.version_id == ident, ChapterDraft.index == index)
    old.is_current = False
    content = clean_draft(body.content, index, old.title)
    draft = ChapterDraft(version_id=ident, index=index, rev=max(d.rev for d in all_drafts) + 1, title=old.title, content=content, word_count=count_words(content.partition("\n")[2]), author=body.editor)
    session.add_all([old, draft])
    mark_edit(version, index, session)
    log_action(session, version.project_id, ident, "chapter_edit", body.editor, index=index, before=old.content, after=content)
    session.commit()
    session.refresh(draft)
    runner.enqueue(version.project_id, ident)
    return draft


@router.post("/versions/{ident}/chapters/{index}/regenerate", status_code=202)
async def regenerate(ident: int, index: int, body: Instruction, session: Session = Depends(get_session)):
    version = require_version(ident, session)
    editable(version, {"awaiting_review"})
    old = find_draft(ident, index)
    mark_edit(version, index, session)
    log_action(session, version.project_id, ident, "chapter_regenerate", body.editor, index=index, instruction=body.instruction, before_draft_id=old.id)
    session.commit()
    runner.enqueue(version.project_id, ident)
    return {"status": "queued"}


@router.post("/versions/{ident}/chapters/{index}/accept")
def accept(ident: int, index: int, body: ActionInput, session: Session = Depends(get_session)):
    version = require_version(ident, session)
    editable(version, {"awaiting_review"})
    draft = find_draft(ident, index)
    reviews = rows(ChapterReview, ChapterReview.draft_id == draft.id, order=ChapterReview.id.desc())
    if not reviews:
        raise HTTPException(409, "审核尚未完成")
    review = reviews[0]
    review.editor_accepted = True
    version.stale_chapters = [n for n in version.stale_chapters if n != index]
    session.add_all([review, version])
    log_action(session, version.project_id, ident, "chapter_accept", body.editor, index=index, draft_id=draft.id, verdict=review.verdict, reason=body.reason)
    session.commit()
    return {"status": "accepted"}


@router.post("/versions/{ident}/review", status_code=202)
async def review(ident: int, body: ActionInput, session: Session = Depends(get_session)):
    version = require_version(ident, session)
    editable(version, {"awaiting_review"})
    version.online_metrics = {**version.online_metrics, "review_request": version.online_metrics.get("review_request", 0) + 1}
    version.status, version.current_node = "queued", "N7"
    session.add(version)
    log_action(session, version.project_id, ident, "review_request", body.editor, reason=body.reason)
    session.commit()
    runner.enqueue(version.project_id, ident)
    return {"status": "queued"}


@router.post("/versions/{ident}/retry", status_code=202)
async def retry(ident: int, body: ActionInput, session: Session = Depends(get_session)):
    version = require_version(ident, session)
    editable(version, {"failed"})
    version.status, version.error = "queued", None
    session.add(version)
    log_action(session, version.project_id, ident, "version_retry", body.editor, node=version.current_node)
    session.commit()
    runner.enqueue(version.project_id, ident)
    return {"status": "queued"}


@router.post("/versions/{ident}/submit")
def submit(ident: int, body: ActionInput, session: Session = Depends(get_session)):
    version = require_version(ident, session)
    editable(version, {"awaiting_review"})
    drafts = current_drafts(ident)
    if len(drafts) != version.total_chapters:
        raise HTTPException(409, "还有章节未生成")
    version.status = "submitted"
    session.add(version)
    log_action(session, version.project_id, ident, "version_submit", body.editor, draft_ids=[d.id for d in drafts], stale_chapters=version.stale_chapters, reason=body.reason)
    session.commit()
    return {"status": "submitted"}


@router.post("/versions/{ident}/abandon")
def abandon(ident: int, body: ActionInput, session: Session = Depends(get_session)):
    version = require_version(ident, session)
    editable(version, {"failed", "awaiting_outline", "awaiting_review", "awaiting_direction_confirmation"})
    version.status = "abandoned"
    session.add(version)
    log_action(session, version.project_id, ident, "version_abandon", body.editor, reason=body.reason)
    session.commit()
    return {"status": "abandoned"}


@router.get("/versions/{ident}/export")
def export(ident: int, format: str = "txt", session: Session = Depends(get_session)):
    version = require_version(ident, session)
    if format not in {"txt", "docx"}:
        raise HTTPException(422, "只支持txt或docx")
    project = session.get(Project, version.project_id)
    sources = rows(SourceChapter, SourceChapter.project_id == project.id, order=SourceChapter.index)
    text = "\n\n".join([f"{c.title}\n\n{c.content}" for c in sources] + [d.content for d in current_drafts(ident)])
    if project.is_demo:
        text = "【演示数据，仅用于验证操作流程】\n\n" + text
    if format == "txt":
        content, media = text.encode("utf-8-sig"), "text/plain; charset=utf-8"
    else:
        doc = Document()
        doc.add_heading(project.title, 0)
        for line in text.splitlines():
            doc.add_paragraph(line)
        buf = io.BytesIO()
        doc.save(buf)
        content, media = buf.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(content=content, media_type=media, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(project.title, safe='')}-v{ident}.{format}"})
