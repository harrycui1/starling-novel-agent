"""Deterministic fixtures for explicit demo mode; never used in live mode."""
import json


def respond(name, value):
    def direction(trope):
        return {"title": f"雨夜{trope}之局", "hook": "从遗失账册找到破局入口", "core_conflict": "林舟与沈砚因账册真相而冲突", "main_trope": trope, "secondary_tropes": [], "payoff_plan": ["找到证据", "当面对质", "公开真相"], "ending": "真相公开，冲突收束", "uses_foreshadows": [], "new_characters": [], "differentiation": f"以{trope}为主要路径", "synopsis": "林舟沿着账册留下的线索，逐步找出真相，与沈砚当面对质。", "continuation_start": "接原文雨夜账册悬念，林舟继续核对账册。"}
    if name == "n1_understand":
        result = {"synopsis": "林舟追查雨夜账册，与沈砚对峙。", "characters": [{"name": "林舟", "role": "主角", "description": "谨慎查证"}, {"name": "沈砚", "role": "对手", "description": "隐瞒账册真相"}], "ending": "雨夜账册留下未解的线索。"}
    elif name == "n2_directions":
        result = {"directions": [direction(t) for t in ["打脸", "复仇", "揭秘"]]}
    elif name == "n3_manual":
        result = direction("揭秘")
        result["synopsis"] = value["manual_text"]
    elif name == "n4_outline":
        result = {"arc_summary": "追查账册并揭开真相，完成收束。", "new_characters": [], "chapters": [{"index": i, "title": f"雨中线索{i}", "function": "收束" if i == value["start"] + value["count"] - 1 else "冲突升级", "summary": "账册线索推进，双方当面对质。", "events": ["核对账册", "找出关键证据", "与沈砚对质"], "payoff": "取得新的证据", "hook": "门被推开。", "foreshadow_ops": [], "target_words": value["target_words"] // value["count"]} for i in range(value["start"], value["start"] + value["count"])]}
    elif name in {"n6_write_chapter", "n6_rewrite_chapter"}:
        p = value["context"]["plan"]
        paragraph = "他把账册摊开，沿着模糊的墨迹逐行核对。窗外的雨没有停，门内只剩纸页翻动的声音。他按住纸角，将找到的痕迹同先前的记录比对，终于找到了缺失的一页。"
        target = p["target_words"]
        narration = paragraph * (target // len(paragraph) + 2)
        result = narration[:max(0, target - 5)] + "\n门被推开。"
        return f"第{p['index']}章 {p['title']}\n\n" + result
    elif name == "n7_review":
        result = {"chapters": [{"index": c["index"], "verdict": "pass", "consistency_issues": [], "plan_deviation": [], "pacing_issues": [], "ai_flavor_issues": [], "hook_ok": True, "payoff_ok": True, "fix_suggestions": []} for c in value["context"]["written_chapters"]]}
    else:
        raise ValueError(f"未知演示节点：{name}")
    return json.dumps(result, ensure_ascii=False)
