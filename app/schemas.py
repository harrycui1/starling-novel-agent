from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceCharacter(Schema):
    name: str = Field(min_length=1)
    role: str
    description: str


class SourceSummary(Schema):
    synopsis: str = Field(min_length=1)
    characters: list[SourceCharacter] = Field(min_length=1)
    ending: str = Field(min_length=1)


class NewCharacter(Schema):
    name: str = Field(min_length=1)
    purpose: str


class Direction(Schema):
    title: str = Field(min_length=1)
    hook: str
    core_conflict: str
    main_trope: str = Field(min_length=1)
    secondary_tropes: list[str]
    payoff_plan: list[str]
    ending: str
    uses_foreshadows: list[str] = []
    new_characters: list[NewCharacter]
    differentiation: str
    synopsis: str
    continuation_start: str = ""


class Directions(Schema):
    directions: list[Direction]


class ForeshadowOp(Schema):
    id: str
    op: Literal["payoff", "plant"]
    note: str


class OutlineChapter(Schema):
    index: int
    title: str
    function: Literal["铺垫", "冲突升级", "爽点兑现", "反转", "高潮", "收束"]
    summary: str
    payoff: str | None
    hook: str
    foreshadow_ops: list[ForeshadowOp] = []
    events: list[str] = []
    target_words: int = Field(default=0, ge=0)


class Outline(Schema):
    arc_summary: str
    chapters: list[OutlineChapter] = Field(min_length=1)
    new_characters: list[NewCharacter]


class Issue(Schema):
    severity: Literal["low", "mid", "high"]
    quote: str = Field(max_length=20)
    reason: str
    fix_suggestions: list[str] = []


class ReviewResult(Schema):
    verdict: Literal["pass", "revise", "block"]
    consistency_issues: list[Issue]
    plan_deviation: list[Issue]
    pacing_issues: list[Issue]
    ai_flavor_issues: list[Issue]
    hook_ok: bool
    payoff_ok: bool
    fix_suggestions: list[str]


class ChapterFeedback(ReviewResult):
    index: int


class ManuscriptReview(Schema):
    chapters: list[ChapterFeedback]


class CreateProject(Schema):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=200000)
    genre_tags: list[str] = []
    channel: str = "default"
    editor: str = "local-editor"


class CreateVersion(Schema):
    source: Literal["candidate", "edited", "manual"]
    candidate_id: int | None = None
    direction: Direction | None = None
    manual_text: str | None = None
    target_words: int = Field(default=20000, ge=1000, le=100000)
    reason: str = ""
    editor: str = "local-editor"


class EditOutline(Schema):
    outline: Outline
    editor: str = "local-editor"


class EditChapter(Schema):
    content: str = Field(min_length=1, max_length=50000)
    editor: str = "local-editor"


class Instruction(Schema):
    instruction: str = Field(min_length=1, max_length=10000)
    editor: str = "local-editor"


class ActionInput(Schema):
    editor: str = "local-editor"
    reason: str = ""
