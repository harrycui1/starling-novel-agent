from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(Schema):
    chapter: int
    quote: str = Field(min_length=1, max_length=40)
    verified: bool | None = None


class Character(Schema):
    name: str = Field(min_length=1)
    aliases: list[str] = []
    role: Literal["protagonist", "deuteragonist", "antagonist", "supporting", "minor"]
    personality: list[str] = []
    speech_style: str = ""
    goal_now: str = ""
    status_now: dict[str, str] = {}
    addressing: dict[str, str] = {}
    evidence: list[Evidence] = []


class Relation(Schema):
    a: str
    b: str
    kind: str
    stance_a_to_b: Literal["友好", "中立", "敌意", "未知"]
    note: str
    evidence: list[Evidence] = []


class WorldRule(Schema):
    rule: str
    evidence: list[Evidence]


class TimelineEvent(Schema):
    chapter: int
    event: str


class Foreshadow(Schema):
    id: str
    content: str
    planted_in: int
    status: Literal["open", "paid_off", "dropped"] = "open"
    paid_off_in: int | None = None
    plan_note: str | None = None


class StyleProfile(Schema):
    pov: Literal["第一人称", "第三人称限知", "第三人称全知", "多视角"]
    tense_and_voice: str
    dialogue_ratio: float = Field(default=0, ge=0, le=1)
    avg_sentence_len: float = 0
    avg_paragraph_len: float = 0
    tone: list[str] = []
    sample_passages: list[str] = []


class Digest(Schema):
    chapter: int
    title: str
    digest: str


class StoryBible(Schema):
    genre_tags: list[str]
    selling_points: list[str]
    logline: str
    characters: list[Character] = Field(min_length=1)
    relations: list[Relation]
    world_rules: list[WorldRule]
    timeline: list[TimelineEvent]
    foreshadows: list[Foreshadow]
    style: StyleProfile
    chapter_digests: list[Digest]


class Foreshadows(Schema):
    foreshadows: list[Foreshadow]


class NewCharacter(Schema):
    name: str = Field(min_length=1)
    purpose: str


class Direction(Schema):
    title: str = Field(min_length=1)
    hook: str
    core_conflict: str
    main_trope: str
    secondary_tropes: list[str]
    payoff_plan: list[str]
    ending: str
    uses_foreshadows: list[str]
    new_characters: list[NewCharacter]
    differentiation: str
    synopsis: str


class Directions(Schema):
    directions: list[Direction]


class Score(Schema):
    reason: str
    score: int = Field(ge=1, le=5)


class JudgeResult(Schema):
    consistency: Score
    payoff_strength: Score
    capacity: Score
    novelty: Score
    channel_fit: Score


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
    foreshadow_ops: list[ForeshadowOp]


class Outline(Schema):
    arc_summary: str
    chapters: list[OutlineChapter] = Field(min_length=1)
    new_characters: list[NewCharacter]


class Scene(Schema):
    location: str
    characters: list[str]
    beats: list[str] = Field(min_length=3, max_length=6)
    purpose: str


class ChapterPlan(Schema):
    index: int
    title: str
    pov_character: str
    scenes: list[Scene] = Field(min_length=2, max_length=4)
    payoff_detail: str | None
    foreshadow_ops: list[ForeshadowOp]
    ending_beat: str
    target_words: int = Field(gt=0)


class ChapterPlans(Schema):
    plans: list[ChapterPlan]


class Issue(Schema):
    severity: Literal["low", "mid", "high"]
    quote: str = Field(max_length=20)
    reason: str


class ReviewResult(Schema):
    verdict: Literal["pass", "revise", "block"]
    consistency_issues: list[Issue]
    plan_deviation: list[Issue]
    pacing_issues: list[Issue]
    ai_flavor_issues: list[Issue]
    hook_ok: bool
    payoff_ok: bool
    fix_suggestions: list[str]


class CharacterUpdate(Schema):
    name: str
    goal_now: str | None = None
    status_now: dict[str, str] = {}
    addressing: dict[str, str] = {}


class BiblePatch(Schema):
    chapter_digest: str
    timeline_add: list[TimelineEvent]
    character_updates: list[CharacterUpdate]
    relation_updates: list[Relation]
    foreshadow_updates: list[Foreshadow]


class CreateProject(Schema):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=200000)
    genre_tags: list[str] = []
    channel: str = "default"
    editor: str = "local-editor"


class CreateVersion(Schema):
    source: Literal["candidate", "edited", "manual", "auto"]
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
