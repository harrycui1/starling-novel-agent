import io
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select
from docx import Document

from app.config import settings
from app.db import get_session
from app.models import Project, SourceChapter, DirectionCandidate, Version
from app.schemas import CreateProject, CreateVersion, ActionInput
from app.services import log_action, rows, source_understanding
from app.checks import count_words, split_chapters, source_index
from app.pipeline.runner import runner

router = APIRouter()


def require_project(project_id, session):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "找不到项目")
    return project


def check_idle(project):
    if runner.busy(project.id):
        raise HTTPException(409, "项目正在运行，请等待完成")


def create_project(body, session):
    if not body.text.strip():
        raise HTTPException(422, "原文不能为空")
    if body.channel not in settings.channels:
        raise HTTPException(422, "未知渠道")
    project = Project(title=body.title, genre_tags=body.genre_tags, channel=body.channel, source_word_count=count_words(body.text), created_by=body.editor, is_demo=settings.mode == "demo")
    session.add(project)
    session.flush()
    previous_index = 0
    for title, content in split_chapters(body.text, settings.channels[body.channel]["chapter_words"]):
        index = max(previous_index + 1, source_index(title, previous_index + 1))
        session.add(SourceChapter(project_id=project.id, index=index, title=title, content=content))
        previous_index = index
    log_action(session, project.id, None, "upload", body.editor, word_count=project.source_word_count, title=project.title)
    session.commit()
    session.refresh(project)
    runner.enqueue(project.id)
    return project


@router.post("/projects", status_code=201)
async def upload_text(body: CreateProject, session: Session = Depends(get_session)):
    return create_project(body, session)


@router.post("/projects/upload", status_code=201)
async def upload_file(file: UploadFile = File(...), title: str = Form(...), genre_tags: str = Form(""), channel: str = Form("default"), editor: str = Form("local-editor"), session: Session = Depends(get_session)):
    raw = await file.read(2_000_001)
    if len(raw) > 2_000_000:
        raise HTTPException(413, "文件不能超过2MB")
    try:
        if (file.filename or "").lower().endswith(".docx"):
            text = "\n".join(p.text for p in Document(io.BytesIO(raw)).paragraphs)
        elif (file.filename or "").lower().endswith((".txt", ".md")):
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("gb18030")
        else:
            raise HTTPException(422, "支持txt、md和docx文件")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "文件无法解析，请检查格式")
    if not text.strip() or len(text) > 200000:
        raise HTTPException(422, "原文须为1至200000字符")
    return create_project(CreateProject(title=title, text=text, genre_tags=[s.strip() for s in genre_tags.split(",") if s.strip()], channel=channel, editor=editor), session)


@router.get("/projects")
def list_projects(session: Session = Depends(get_session)):
    return session.exec(select(Project).order_by(Project.id.desc())).all()


@router.get("/projects/{project_id}")
def detail(project_id: int, session: Session = Depends(get_session)):
    project = require_project(project_id, session)
    return {"project": project, "source_chapters": rows(SourceChapter, SourceChapter.project_id == project_id, order=SourceChapter.index), "understanding": source_understanding(project_id), "directions": rows(DirectionCandidate, DirectionCandidate.project_id == project_id, DirectionCandidate.batch_id == project.active_batch, DirectionCandidate.shortlisted == True, order=DirectionCandidate.id), "versions": rows(Version, Version.project_id == project_id, order=Version.id.desc())}


@router.post("/projects/{project_id}/directions/regenerate", status_code=202)
async def regenerate(project_id: int, body: ActionInput, session: Session = Depends(get_session)):
    project = require_project(project_id, session)
    check_idle(project)
    if project.status != "awaiting_direction":
        raise HTTPException(409, "原文理解尚未完成")
    old = rows(DirectionCandidate, DirectionCandidate.project_id == project_id, DirectionCandidate.batch_id == project.active_batch, DirectionCandidate.shortlisted == True)
    log_action(session, project_id, None, "direction_reject", body.editor, candidate_ids=[d.id for d in old], reason=body.reason)
    log_action(session, project_id, None, "direction_regenerate", body.editor, previous_batch=project.active_batch)
    project.status, project.current_node = "queued", "N2"
    session.add(project)
    session.commit()
    runner.enqueue(project_id)
    return {"status": "queued"}


@router.post("/projects/{project_id}/retry", status_code=202)
async def retry(project_id: int, body: ActionInput, session: Session = Depends(get_session)):
    project = require_project(project_id, session)
    check_idle(project)
    if project.status != "failed":
        raise HTTPException(409, "只有失败任务可以重试")
    project.status, project.error = "queued", None
    session.add(project)
    log_action(session, project_id, None, "project_retry", body.editor, node=project.current_node)
    session.commit()
    runner.enqueue(project_id)
    return {"status": "queued"}


@router.post("/projects/{project_id}/versions", status_code=201)
async def create_version(project_id: int, body: CreateVersion, session: Session = Depends(get_session)):
    project = require_project(project_id, session)
    check_idle(project)
    if project.status != "awaiting_direction":
        raise HTTPException(409, "请等待方向生成完成")
    shown = rows(DirectionCandidate, DirectionCandidate.project_id == project_id, DirectionCandidate.batch_id == project.active_batch, DirectionCandidate.shortlisted == True, order=DirectionCandidate.id)
    candidate = None
    if body.source in {"candidate", "edited"}:
        candidate = next((d for d in shown if d.id == body.candidate_id), None)
    if body.source != "manual" and candidate is None:
        raise HTTPException(422, "请选择当前批次的有效方向")
    if body.source == "edited" and body.direction is None:
        raise HTTPException(422, "缺少编辑后的方向")
    if body.source == "manual":
        if not body.manual_text or not body.manual_text.strip():
            raise HTTPException(422, "请输入方向描述")
        direction = {"manual_text": body.manual_text}
    else:
        direction = body.direction.model_dump() if body.source == "edited" else candidate.data
    version = Version(project_id=project_id, direction_source=body.source, direction_candidate_id=candidate.id if candidate else None, direction=direction, target_words=body.target_words, current_node="N3" if body.source == "manual" else "N4")
    session.add(version)
    session.flush()
    action = {"candidate": "direction_select", "edited": "direction_edit", "manual": "direction_manual"}[body.source]
    log_action(session, project_id, version.id, action, body.editor, displayed_candidate_ids=[d.id for d in shown], selected_candidate_id=candidate.id if candidate else None, reason=body.reason, before=candidate.data if candidate else None, after=direction)
    if body.source == "edited":
        log_action(session, project_id, version.id, "direction_select", body.editor, displayed_candidate_ids=[d.id for d in shown], selected_candidate_id=candidate.id, reason=body.reason)
    session.commit()
    session.refresh(version)
    runner.enqueue(project_id, version.id)
    return version
