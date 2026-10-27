from app.checks import style_stats, verify_bible
from app.llm.structured import structured
from app.models import StoryBibleSnapshot
from app.schemas import StoryBible
from app.services import save
from app.pipeline.context import NodeResult


async def run(ctx):
    chapters = ctx.sources
    inputs = {"chapters": [{"index": c.index, "title": c.title, "content": c.content} for c in chapters], "genre_tags": ctx.project.genre_tags}
    def validate(bible):
        verify_bible(bible, chapters)
        if [d.chapter for d in bible.chapter_digests] != [c.index for c in chapters]:
            raise ValueError("每个原文章节必须各有一份摘要，章号、顺序与输入完全一致")
    bible = await structured("n1_bible_extract", inputs, StoryBible, ctx.project_id, validate=validate)
    for digest, chapter in zip(bible.chapter_digests, chapters):
        digest.title = chapter.title
    bible.state_inventory_complete = True
    for state in [*bible.props, *bible.scene_states]:
        state.updated_in = chapters[-1].index
    source = "\n\n".join(c.content for c in chapters)
    for key, value in style_stats(source).items():
        setattr(bible.style, key, value)
    paragraphs = [p.strip() for p in source.splitlines() if len(p.strip()) >= 80]
    passages = paragraphs or [source]
    chosen = sorted(passages, key=lambda p: p.count('“'), reverse=True)[:1]
    chosen += [p for p in passages if p not in chosen][:2]
    bible.style.sample_passages = [p[:400] for p in chosen]
    warnings = verify_bible(bible, chapters)
    save(StoryBibleSnapshot(project_id=ctx.project_id, after_chapter=chapters[-1].index, data=bible.model_dump(), warnings=warnings))
    return NodeResult("generating_directions", "N2")
