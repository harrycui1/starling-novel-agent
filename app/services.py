from sqlmodel import Session, select

from app.db import engine
from app.models import ChapterDraft, ChapterPlanRow, EditorAction, OutlineRevision, PipelineEvent, SourceUnderstanding, StoryBibleSnapshot


def one(model, ident):
    with Session(engine) as s:
        return s.get(model, ident)


def rows(model, *conditions, order=None):
    with Session(engine) as s:
        query = select(model).where(*conditions)
        if order is not None:
            query = query.order_by(order)
        return list(s.exec(query))


def save(*items):
    with Session(engine) as s:
        for item in items:
            s.add(item)
        s.commit()
        for item in items:
            s.refresh(item)


def log_action(s, project_id, version_id, action, editor="local-editor", **payload):
    s.add(EditorAction(project_id=project_id, version_id=version_id, action=action, editor=editor, payload=payload))


def emit(project_id, version_id, kind, **data):
    save(PipelineEvent(project_id=project_id, version_id=version_id, kind=kind, data=data))


def latest_outline(version_id):
    result = rows(OutlineRevision, OutlineRevision.version_id == version_id, order=OutlineRevision.rev.desc())
    return result[0] if result else None


def current_drafts(version_id):
    return rows(ChapterDraft, ChapterDraft.version_id == version_id, ChapterDraft.is_current == True, order=ChapterDraft.index)


def latest_plans(version_id):
    plans = rows(ChapterPlanRow, ChapterPlanRow.version_id == version_id, order=ChapterPlanRow.generation.desc())
    return sorted([p for p in plans if p.generation == plans[0].generation], key=lambda p: p.index) if plans else []


def source_understanding(project_id):
    summaries = rows(SourceUnderstanding, SourceUnderstanding.project_id == project_id, order=SourceUnderstanding.id.desc())
    if summaries:
        return summaries[0]
    snapshots = rows(StoryBibleSnapshot, StoryBibleSnapshot.project_id == project_id, StoryBibleSnapshot.version_id == None, order=StoryBibleSnapshot.id.desc())
    if snapshots:
        old = snapshots[0].data
        return SourceUnderstanding(project_id=project_id, data={
            "synopsis": old.get("logline", ""),
            "characters": [{"name": c["name"], "role": c["role"], "description": "、".join(c.get("personality", []))} for c in old.get("characters", [])],
            "ending": "",
        })
    return None


def store_draft(version_id, index, title, content, author="ai"):
    from app.checks import count_words
    with Session(engine) as s:
        all_drafts = list(s.exec(select(ChapterDraft).where(ChapterDraft.version_id == version_id, ChapterDraft.index == index)))
        for old in all_drafts:
            old.is_current = False
            s.add(old)
        draft = ChapterDraft(version_id=version_id, index=index, rev=max((d.rev for d in all_drafts), default=-1) + 1, title=title, content=content, word_count=count_words(content.partition("\n")[2]), author=author)
        s.add(draft)
        s.commit()
        s.refresh(draft)
        return draft
