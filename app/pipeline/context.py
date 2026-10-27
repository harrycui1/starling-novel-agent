from dataclasses import dataclass

from app.config import settings
from app.models import Project, Version, SourceChapter
from app.services import one, rows, current_drafts, latest_outline


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


def source_context(ctx):
    return [{"index": c.index, "title": c.title, "content": c.content} for c in ctx.sources]


def manuscript_context(ctx):
    return {
        "source_chapters": source_context(ctx),
        "written_chapters": [{"index": d.index, "title": d.title, "content": d.content} for d in current_drafts(ctx.version_id)],
        "outline": latest_outline(ctx.version_id).data,
        "direction": ctx.version.direction,
    }


def build_write_context(ctx, plan):
    context = manuscript_context(ctx)
    context["written_chapters"] = [d for d in context["written_chapters"] if d["index"] < plan.index]
    context["plan"] = plan.model_dump()
    context["hard_requirements"] = {
        "target_words": plan.target_words,
        "word_tolerance": settings.word_tolerance,
        "ending_beat": plan.hook,
        "banned_endings": settings.banned_endings_file.read_text().splitlines(),
        "banned_words": settings.banned_words_file.read_text().splitlines(),
    }
    return context
