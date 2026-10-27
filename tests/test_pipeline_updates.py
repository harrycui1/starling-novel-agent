import json
from types import SimpleNamespace


def bible_fixture():
    from app.llm.demo import respond
    from app.schemas import StoryBible
    return StoryBible.model_validate_json(respond("n1_bible_extract", {"chapters": [{"index": 1, "title": "雨夜", "content": "林舟把铜钥匙压在账页上。沈砚关上门。"}], "genre_tags": ["悬疑"]}))


def plan_fixture():
    from app.schemas import ChapterPlan
    return ChapterPlan(index=2, title="线索", pov_character="林舟", scenes=[{"location": "铺子", "characters": ["林舟"], "beats": ["读账册", "核对", "推门"], "purpose": "推进"} for _ in range(2)], payoff_detail=None, foreshadow_ops=[], ending_beat="推门", target_words=2500)


def test_name_fragments_and_length_are_editor_notes(monkeypatch):
    from app.checks import draft_issues
    from app.checks import pseg
    from app.schemas import Character
    bible = bible_fixture()
    bible.characters.append(Character(name="陆敬堂", role="antagonist"))
    bible.style.dialogue_ratio = 0
    monkeypatch.setattr(pseg, "cut", lambda _: [("敬堂", "nr"), ("红印", "nr")])
    issues = draft_issues("第2章 线索\n敬堂拿起红印，敬堂放下红印。", plan_fixture(), bible)
    assert not any("敬堂" in item["detail"] for item in issues)
    assert all(item["verdict"] == "info" for item in issues)
    assert {item["code"] for item in issues} == {"length", "unknown_character"}


def test_state_patch_tracks_props_and_scenes_without_mutating_previous():
    from app.schemas import BiblePatch
    from app.pipeline.nodes.n6_write import merge_patch
    original = bible_fixture()
    patch = BiblePatch(chapter_digest="收起钥匙并开门", timeline_add=[], character_updates=[], relation_updates=[], foreshadow_updates=[], prop_updates=[{"name":"铜钥匙", "holder":"林舟", "location":"林舟袖中", "state":"已收起"}], scene_updates=[{"name":"铺子", "state":"门已打开", "characters":["林舟"]}])
    updated, warnings = merge_patch(original, patch, 2, "线索")
    assert not warnings
    assert original.props[0].location == "账页上"
    assert updated.props[0].location == "林舟袖中" and updated.props[0].updated_in == 2
    assert updated.scene_states[0].state == "门已打开"


def test_scene_budgets_and_review_materials_are_compact(monkeypatch):
    from app.checks import allocate_scene_words
    from app.pipeline import context
    from app.llm.gateway import prompt_template
    plan = allocate_scene_words(plan_fixture())
    bible = bible_fixture()
    bible.style.sample_passages = ["不应进入审核的长风格样例" * 100]
    monkeypatch.setattr(context, "current_drafts", lambda _: [])
    ctx = SimpleNamespace(version_id=1, sources=[SimpleNamespace(content="前文" * 10000)])
    compact = context.build_review_context(ctx, plan, bible)
    assert sum(scene.target_words for scene in plan.scenes) == 2500
    assert len(compact["previous_ending"]) == 800
    assert "sample_passages" not in json.dumps(compact) and "previous_digests" not in compact
    _, prompt = prompt_template("n6_write_chapter", {"context":{"characters": [{"name":"林舟"}], "previous_chapter":"上一章原文", "plan":plan.model_dump()}})
    assert '"previous_chapter":' not in prompt
    assert prompt.index("上一章完整正文") < prompt.index("本章细纲与场景字数预算")
    assert "我不认为这是一个好主意" in prompt
