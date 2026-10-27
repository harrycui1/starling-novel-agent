from app.checks import style_stats, verify_bible
from app.llm.structured import structured
from app.models import StoryBibleSnapshot
from app.schemas import Digest, StoryBible, Foreshadows
from app.services import save
from app.pipeline.context import NodeResult


async def run(ctx):
    chapters = ctx.sources
    digests = []
    for c in chapters:
        result = await structured("n1_chapter_digest", {"chapter": c.model_dump()}, Digest, ctx.project_id)
        result.chapter, result.title = c.index, c.title
        digests.append(result)
    inputs = {"chapters": [c.model_dump() for c in chapters], "digests": [d.model_dump() for d in digests], "genre_tags": ctx.project.genre_tags}
    def validate(bible):
        verify_bible(bible, chapters)
    bible = await structured("n1_bible_extract", inputs, StoryBible, ctx.project_id, validate=validate)
    extra = await structured("n1_foreshadows", inputs, Foreshadows, ctx.project_id)
    by_id = {f.id: f for f in bible.foreshadows}
    for f in extra.foreshadows:
        if f.id not in by_id and all(f.content != old.content for old in by_id.values()):
            by_id[f.id] = f
    bible.foreshadows = list(by_id.values())
    source = "\n\n".join(c.content for c in chapters)
    for key, value in style_stats(source).items():
        setattr(bible.style, key, value)
    paragraphs = [p.strip() for p in source.splitlines() if len(p.strip()) >= 80]
    passages = paragraphs or [source]
    chosen = sorted(passages, key=lambda p: p.count('“'), reverse=True)[:1]
    chosen += [p for p in passages if p not in chosen][:2]
    bible.style.sample_passages = [p[:400] for p in chosen]
    bible.chapter_digests = digests
    warnings = verify_bible(bible, chapters)
    save(StoryBibleSnapshot(project_id=ctx.project_id, after_chapter=chapters[-1].index, data=bible.model_dump(), warnings=warnings))
    return NodeResult("generating_directions", "N2")
