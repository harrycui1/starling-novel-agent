from datetime import datetime, timezone

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def now():
    return datetime.now(timezone.utc)


def json_field(factory=dict):
    return Field(default_factory=factory, sa_column=Column(JSON, nullable=False))


class Project(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    genre_tags: list[str] = json_field(list)
    channel: str = "default"
    source_word_count: int
    created_by: str = "local-editor"
    created_at: datetime = Field(default_factory=now)
    status: str = "created"
    current_node: str = "N1"
    error: str | None = None
    active_batch: str | None = None
    is_demo: bool = False


class SourceChapter(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("project_id", "index"),)
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    index: int
    title: str
    content: str


class StoryBibleSnapshot(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    version_id: int | None = Field(default=None, foreign_key="version.id", index=True)
    after_chapter: int
    data: dict = json_field()
    warnings: list[dict] = json_field(list)
    created_at: datetime = Field(default_factory=now)


class DirectionCandidate(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    batch_id: str
    data: dict = json_field()
    judge_scores: dict = json_field()
    shortlisted: bool = False
    score: float = 0


class Version(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    direction_source: str
    direction_candidate_id: int | None = Field(default=None, foreign_key="directioncandidate.id")
    direction: dict = json_field()
    target_words: int = 20000
    status: str = "created"
    current_node: str = "N4"
    current_chapter: int = 0
    total_chapters: int = 0
    error: str | None = None
    stale_chapters: list[int] = json_field(list)
    online_metrics: dict = json_field()
    created_at: datetime = Field(default_factory=now)


class OutlineRevision(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("version_id", "rev"),)
    id: int | None = Field(default=None, primary_key=True)
    version_id: int = Field(foreign_key="version.id", index=True)
    rev: int
    data: dict = json_field()
    author: str = "ai"
    confirmed: bool = False
    warnings: list[str] = json_field(list)


class ChapterPlanRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    version_id: int = Field(foreign_key="version.id", index=True)
    index: int
    generation: int = 1
    data: dict = json_field()


class ChapterDraft(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("version_id", "index", "rev"),)
    id: int | None = Field(default=None, primary_key=True)
    version_id: int = Field(foreign_key="version.id", index=True)
    index: int
    rev: int
    title: str
    content: str
    word_count: int
    author: str = "ai"
    is_current: bool = True


class ChapterReview(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    draft_id: int = Field(foreign_key="chapterdraft.id", index=True)
    verdict: str
    rule_issues: list[dict] = json_field(list)
    llm_review: dict = json_field()
    editor_accepted: bool = False


class EditorAction(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    version_id: int | None = Field(default=None, foreign_key="version.id", index=True)
    editor: str = "local-editor"
    action: str
    payload: dict = json_field()
    created_at: datetime = Field(default_factory=now)


class LLMCall(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    version_id: int | None = Field(default=None, foreign_key="version.id", index=True)
    node: str
    prompt_name: str
    prompt_version: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    success: bool = False
    error: str | None = None
    raw_output_path: str | None = None
    created_at: datetime = Field(default_factory=now)


class PipelineEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    version_id: int | None = Field(default=None, foreign_key="version.id", index=True)
    kind: str
    data: dict = json_field()
    created_at: datetime = Field(default_factory=now)
