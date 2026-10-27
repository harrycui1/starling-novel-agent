"""Readable, ordered materials shared by the fixed pipeline prompts."""
LABELS = {
    "bible": "故事档案", "story_bible_brief": "人物与世界事实", "characters": "人物档案", "other_characters": "其他已登记人物",
    "props": "关键道具当前状态", "scene_states": "场景当前状态", "style": "原文文风", "synopsis": "续写梗概（不含原文回顾）",
    "opening_moment": "首章衔接原文的瞬间", "arc_summary": "已确认的整体走向", "previous_digests": "前情摘要",
    "previous_chapter": "上一章完整正文", "previous_ending": "上一章结尾", "plan": "本章细纲与场景字数预算",
    "chapters": "原文章节或本批章节", "chapter_digests": "逐章摘要", "chapter": "章节", "content": "正文",
    "world_rules": "世界规则", "foreshadows": "伏笔", "relations": "人物关系", "timeline": "已发生事件",
    "direction": "续写方向", "candidates": "待比较方向（顺序已随机打乱）", "candidate_id": "候选ID",
    "outline": "已确认大纲", "scenes": "场景", "beats": "情节节拍", "target_words": "目标字数",
    "chapter_target": "单章目标字数", "hard_requirements": "篇幅与风格要求", "draft": "待审或待改正文",
    "issues": "需修正的问题", "rule_issues": "确定性检查结果", "suggestions": "修改建议", "manual_text": "编辑方向要求",
    "trope_vocab": "允许的主套路词表", "previous_plans": "此前细纲", "genre_tags": "题材标签", "avoid": "避免重复的旧方向",
    "name": "名称", "holder": "当前持有人", "location": "当前位置", "state": "当前状态", "evidence": "原文证据",
    "quote": "引文", "index": "章号", "title": "标题", "role": "人物作用", "goal_now": "当前目标", "status_now": "当前人物状态",
    "addressing": "人物称谓", "speech_style": "说话口吻", "personality": "性格", "aliases": "别名", "logline": "原文梗概",
    "sample_passages": "原文风格样例", "pov_character": "本章视角人物", "ending_beat": "章末停笔瞬间", "purpose": "场景作用",
}


def _material(value, depth):
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            if item == [] or item == {} or item == "":
                continue
            label = LABELS.get(key, key)
            parts.append(f"{'#' * min(depth, 6)} {label} ({key})\n{_material(item, depth + 1)}")
        return "\n\n".join(parts) or "无"
    if isinstance(value, list):
        return "\n\n".join(f"- {i + 1}. {_material(item, depth + 1)}" for i, item in enumerate(value)) or "无"
    if value is None:
        return "未确定；不得自行补充事实"
    return str(value)


def render_sections(payload):
    values = {**payload.get("context", {}), **{k: v for k, v in payload.items() if k != "context"}}
    # Revisions and review notes precede the immediate continuation context.
    ordered = {k: v for k, v in values.items() if k not in {"previous_chapter", "previous_ending", "plan"}}
    for key in ("previous_chapter", "previous_ending", "plan"):
        if key in values:
            ordered[key] = values[key]
    return _material(ordered, 2)
