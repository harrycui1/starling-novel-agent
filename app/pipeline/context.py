import json
from dataclasses import dataclass

from app.config import settings
from app.models import Project, Version, SourceChapter
from app.services import one, rows, version_bible, current_drafts, latest_outline


@dataclass
class NodeContext:
    project_id: int
    version_id: int | None = None

    @property
    def project(self):
        return one(Project, self.project_id)

    @property
    def version(self):
        return one(Version, self.version_id)

    @property
    def sources(self):
        return rows(SourceChapter, SourceChapter.project_id == self.project_id, order=SourceChapter.index)


@dataclass
class NodeResult:
    status: str
    next_node: str


def build_write_context(ctx, plan, bible):
    involved = {plan.pov_character, *(n for scene in plan.scenes for n in scene.characters)}
    brief = bible.model_dump()
    brief["characters"] = [c.model_dump() if c.name in involved else {"name": c.name, "role": c.role} for c in bible.characters]
    brief["foreshadows"] = [f.model_dump() for f in bible.foreshadows if f.status == "open" or f.id in {o.id for o in plan.foreshadow_ops}]
    brief.pop("chapter_digests")
    drafts = [d for d in current_drafts(ctx.version_id) if d.index < plan.index]
    previous = drafts[-1].content if drafts else ctx.sources[-1].content
    digests = [d.model_dump() for d in bible.chapter_digests if d.chapter < plan.index - 1]
    context = {"story_bible_brief": brief, "style": bible.style.model_dump(), "synopsis": ctx.version.direction["synopsis"], "arc_summary": latest_outline(ctx.version_id).data["arc_summary"], "previous_digests": digests, "previous_chapter": previous, "plan": plan.model_dump(), "hard_requirements": {"target_words": plan.target_words, "word_tolerance": settings.word_tolerance, "dialogue_ratio": bible.style.dialogue_ratio, "dialogue_tolerance": settings.dialogue_ratio_tolerance, "ending_beat": plan.ending_beat, "banned_endings": settings.banned_endings_file.read_text().splitlines(), "banned_words": settings.banned_words_file.read_text().splitlines()}}
    # One character per token is a conservative budget for Chinese prose.
    size = lambda: len(json.dumps(context, ensure_ascii=False))
    if size() > settings.context_budget_tokens:
        for digest in digests:
            digest["digest"] = digest["digest"][:100]
    if size() > settings.context_budget_tokens:
        context["style"]["sample_passages"] = bible.style.sample_passages[:1]
        brief["style"]["sample_passages"] = bible.style.sample_passages[:1]
    if size() > settings.context_budget_tokens:
        brief["characters"] = [c if c["name"] in involved else {"name": c["name"]} for c in brief["characters"]]
    if size() > settings.context_budget_tokens:
        raise ValueError("上下文仍超预算；上一章、细纲和硬要求不能裁剪，请增大上下文预算")
    return context
