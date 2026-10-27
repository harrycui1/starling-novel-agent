"""Explicit deterministic demo provider; never used in live mode."""
import json
from app.config import settings


def respond(name, value):
    def direction(trope):
        return {"title": f"雨夜{trope}之局", "hook": "从遗失账册找到破局入口", "core_conflict": "林舟与沈砚因账册真相而冲突", "main_trope": trope, "secondary_tropes": [], "payoff_plan": ["找到证据", "当面对质", "公开真相"], "ending": "真相公开，冲突收束", "uses_foreshadows": [], "new_characters": [], "differentiation": f"以{trope}为主要路径", "synopsis": "林舟沿着账册留下的线索，逐步找出真相，与沈砚当面对质。"}
    if name == "n1_chapter_digest":
        c = value["chapter"]
        result = {"chapter": c["index"], "title": c["title"], "digest": c["content"][:300]}
    elif name == "n1_bible_extract":
        c = value["chapters"][0]
        result = {"genre_tags": value["genre_tags"], "selling_points": ["账册悬念"], "logline": "林舟追查雨夜账册。", "characters": [{"name": "林舟", "role": "protagonist", "personality": ["谨慎"], "evidence": [{"chapter": c["index"], "quote": "林舟"}]}, {"name": "沈砚", "role": "antagonist", "evidence": [{"chapter": c["index"], "quote": "沈砚"}]}], "relations": [], "world_rules": [], "timeline": [], "foreshadows": [], "style": {"pov": "第三人称限知", "tense_and_voice": "克制叙述"}, "chapter_digests": value["digests"]}
    elif name == "n1_foreshadows":
        result = {"foreshadows": []}
    elif name == "n2_directions":
        result = {"directions": [direction(t) for t in settings.trope_vocab[:value["count"]]]}
    elif name == "n3_judge":
        result = {k: {"reason": "演示评分：符合现有材料", "score": 4} for k in settings.judge_weights}
    elif name == "n3_manual":
        result = direction(settings.trope_vocab[0])
        result["synopsis"] = value["manual_text"]
    elif name == "n4_outline":
        result = {"arc_summary": "追查账册并揭开真相，完成收束。", "new_characters": [], "chapters": [{"index": i, "title": f"雨中线索{i}", "function": "收束" if i == value["start"] + value["count"] - 1 else "冲突升级", "summary": "账册线索推进，双方当面对质。", "payoff": "取得新的证据", "hook": "门后传来声响。", "foreshadow_ops": []} for i in range(value["start"], value["start"] + value["count"])]}
    elif name == "n5_chapter_plan":
        result = {"plans": [{"index": c["index"], "title": c["title"], "pov_character": "林舟", "scenes": [{"location": "屋内", "characters": ["林舟", "沈砚"], "beats": ["看到账册", "核对证据", "开始对质"], "purpose": "推进冲突"} for _ in range(2)], "payoff_detail": c["payoff"], "foreshadow_ops": c["foreshadow_ops"], "ending_beat": "门被推开。", "target_words": value["chapter_target"]} for c in value["chapters"]]}
    elif name in {"n6_write_chapter", "n6_rewrite_chapter"}:
        p = value["context"]["plan"]
        paragraph = "他把账册摊开，沿着模糊的墨迹逐行核对。窗外的雨没有停，门内只剩纸页翻动的声音。他按住纸角，将找到的痕迹同先前的记录比对，终于找到了缺失的一页。\n\n"
        target = p["target_words"]
        ratio = value["context"]["hard_requirements"]["dialogue_ratio"]
        quote = "“" + ("请把那一页翻过来。" * target)[:round(target * ratio)] + "”"
        narration = paragraph.replace("\n", "") * (target // 50 + 2)
        result = narration[:max(0, target - len(quote) - 5)] + "\n" + quote + "\n门被推开。"
        return f"第{p['index']}章 {p['title']}\n\n" + result
    elif name == "n6_review_chapter":
        result = {"verdict": "pass", "consistency_issues": [], "plan_deviation": [], "pacing_issues": [], "ai_flavor_issues": [], "hook_ok": True, "payoff_ok": True, "fix_suggestions": []}
    elif name == "n6_bible_update":
        result = {"chapter_digest": "核对账册，找到线索。", "timeline_add": [], "character_updates": [], "relation_updates": [], "foreshadow_updates": []}
    else:
        raise ValueError(f"未知演示节点：{name}")
    return json.dumps(result, ensure_ascii=False)
