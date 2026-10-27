import math
import re

import jieba.posseg as pseg

from app.config import settings


def count_words(text):
    return len(re.sub(r"\s", "", text))


def split_chapters(text, size=2500):
    headings = list(re.finditer(r"(?m)^\s*第[零〇一二三四五六七八九十百千万两\d]+章[^\n]*", text))
    if headings:
        result = []
        preface = text[:headings[0].start()].strip()
        for i, match in enumerate(headings):
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            content = text[match.end():end].strip()
            if i == 0 and preface:
                content = preface + "\n\n" + content
            result.append((match.group().strip(), content))
        return result
    result, current = [], ""
    paragraphs = text.splitlines()
    for para in paragraphs:
        pieces = re.split(r"(?<=[。！？])", para) if len(para) > size else [para]
        for piece in pieces:
            # A manuscript can be one long line without any sentence punctuation.
            for offset in range(0, max(len(piece), 1), size):
                segment = piece[offset:offset + size]
                if len(current) >= size:
                    result.append((f"原文片段 {len(result) + 1}", current.strip()))
                    current = ""
                current += segment + "\n"

    if current.strip():
        result.append((f"原文片段 {len(result) + 1}", current.strip()))
    return result


def style_stats(text):
    total = max(count_words(text), 1)
    dialogue = sum(count_words(part) for match in re.findall(r'“([^”]*)”|「([^」]*)」|"([^"\n]*)"', text) for part in match if part)
    sentences = [s for s in re.split(r"[。！？!?]+", text) if s.strip()]
    paragraphs = [p for p in text.splitlines() if p.strip()]
    return {"dialogue_ratio": min(dialogue / total, 1), "avg_sentence_len": total / max(len(sentences), 1), "avg_paragraph_len": total / max(len(paragraphs), 1)}


def chapter_count(target, channel):
    return max(settings.min_chapters, min(settings.max_chapters, math.floor(target / settings.channels[channel]["chapter_words"] + .5)))


def normalize(text):
    return re.sub(r"[\W_]", "", text)


def verify_bible(bible, chapters):
    warnings = []
    sources = {c.index: normalize(c.content) for c in chapters}
    for category in ("characters", "relations", "world_rules", "props", "scene_states"):
        for item in getattr(bible, category):
            for evidence in item.evidence:
                evidence.verified = bool(normalize(evidence.quote)) and normalize(evidence.quote) in sources.get(evidence.chapter, "")
                if not evidence.verified:
                    warnings.append({"type": "unverified", "entry": getattr(item, "name", getattr(item, "rule", category)), "quote": evidence.quote, "chapter": evidence.chapter})
    if not any(c.role == "protagonist" for c in bible.characters):
        raise ValueError("原文档案没有主角")
    if len({c.name for c in bible.characters}) != len(bible.characters):
        raise ValueError("档案存在重名角色")
    for c in bible.characters:
        if not any(e.verified for e in c.evidence):
            raise ValueError(f"角色 {c.name} 缺少可核对的原文证据")
    return warnings


def validate_direction(direction, bible):
    if direction.main_trope not in settings.trope_vocab:
        raise ValueError("主套路不在词表中")
    if set(direction.uses_foreshadows) - {f.id for f in bible.foreshadows}:
        raise ValueError("方向引用了未知伏笔")
    validate_new_characters(direction.new_characters, bible)


def validate_new_characters(characters, bible):
    names = [c.name for c in characters]
    existing = {c.name for c in bible.characters} | {a for c in bible.characters for a in c.aliases}
    if len(set(names)) != len(names) or set(names) & existing:
        raise ValueError("新增角色重名或与现有角色、别名冲突")


def similarity(a, b):
    grams = lambda s: {s[i:i + 3] for i in range(max(1, len(s) - 2))}
    x, y = grams(normalize(a)), grams(normalize(b))
    return len(x & y) / max(len(x | y), 1)


def outline_issues(outline, direction, start, count):
    issues = []
    if [c.index for c in outline.chapters] != list(range(start, start + count)):
        issues.append("章号必须连续，章节数必须等于代码指定值")
    if outline.chapters[0].function == "铺垫":
        issues.append("首章必须承接原文并推进冲突")
    payoffs = [i for i, c in enumerate(outline.chapters) if c.payoff]
    if not payoffs or any(b - a - 1 > settings.max_gap_between_payoffs for a, b in zip(payoffs, payoffs[1:])):
        issues.append("爽点间隔过长或没有爽点")
    if outline.chapters[-1].function != "收束":
        issues.append("末章须明确收束结局")
    if any(not c.hook.strip() for c in outline.chapters[:-1]):
        issues.append("非末章缺少章末钩子")
    paid = {op.id for c in outline.chapters for op in c.foreshadow_ops if op.op == "payoff"}
    if set(direction.uses_foreshadows) - paid:
        issues.append("未安排回收选中方向的伏笔")
    return issues


def allocate_scene_words(plan):
    result = plan.model_copy(deep=True)
    missing = [scene for scene in result.scenes if scene.target_words is None]
    assigned = sum(scene.target_words or 0 for scene in result.scenes)
    if missing:
        remaining = result.target_words - assigned
        if remaining < len(missing):
            raise ValueError("场景字数分配已超过章节目标")
        each, extra = divmod(remaining, len(missing))
        for i, scene in enumerate(missing):
            scene.target_words = each + (i < extra)
    return result


def validate_plans(plans, outline, bible, target):
    if [p.index for p in plans] != [c.index for c in outline.chapters]:
        raise ValueError("细纲章号与大纲不一致")
    names = {c.name for c in bible.characters}
    for plan, chapter in zip(plans, outline.chapters):
        if any(scene.target_words is None for scene in plan.scenes) or abs(sum(scene.target_words for scene in plan.scenes) - plan.target_words) > plan.target_words * .1:
            raise ValueError(f"第{plan.index}章场景字数合计须在章节目标的±10%以内")
        if {plan.pov_character, *(n for scene in plan.scenes for n in scene.characters)} - names:
            raise ValueError("细纲使用了未经确认的角色")
        if {(op.id, op.op) for op in chapter.foreshadow_ops} - {(op.id, op.op) for op in plan.foreshadow_ops}:
            raise ValueError("细纲遗漏大纲伏笔操作")
    if abs(sum(p.target_words for p in plans) - target) > target * .1:
        raise ValueError("细纲总字数偏差超过10%")


def clean_draft(text, index, title):
    lines = text.strip().splitlines()
    lines = [line for line in lines if not re.match(r"^(?:以下是|字数统计|本章共|【(?:分析|自检)|```)", line.strip())]
    if lines and re.match(r"^第.+章", lines[0]):
        lines.pop(0)
    return f"第{index}章 {title}\n\n" + "\n".join(lines).strip()


def draft_issues(text, plan, bible):
    issues = []
    body = text.partition("\n")[2]
    def add(code, detail, level="revise"):
        issues.append({"code": code, "detail": detail, "verdict": level})
    if abs(count_words(body) - plan.target_words) > plan.target_words * settings.word_tolerance:
        add("length", f"正文{count_words(body)}字，目标{plan.target_words}字", "info")
    last = "\n".join([p for p in body.splitlines() if p.strip()][-3:])
    for phrase in settings.banned_endings_file.read_text().splitlines():
        if phrase and phrase in last:
            add("ending", f"结尾禁用表达：{phrase}")
    for phrase in settings.banned_words_file.read_text().splitlines():
        if phrase and body.count(phrase) > settings.banned_word_threshold:
            add("phrase", f"高频词：{phrase}")
    if abs(style_stats(body)["dialogue_ratio"] - bible.style.dialogue_ratio) > settings.dialogue_ratio_tolerance:
        add("dialogue", "对话占比偏离原文")
    known = {c.name for c in bible.characters} | {a for c in bible.characters for a in c.aliases}
    warned = set()
    for word, tag in pseg.cut(body):
        if word not in warned and tag == "nr" and len(word) >= 2 and body.count(word) >= 2 and not any(word in name for name in known):
            warned.add(word)
            add("unknown_character", f"疑似未登记人名：{word}，需人工核对", "info")
    return issues


def merge_verdict(issues, review):
    if review.verdict == "block":
        return "block"
    if review.verdict == "revise" or any(i["verdict"] in {"revise", "block"} for i in issues):
        return "revise"
    if any(i.severity == "high" for i in review.consistency_issues) or not review.hook_ok or not review.payoff_ok:
        return "revise"
    return "pass"


def source_index(title, fallback):
    match = re.match(r"第([零〇一二三四五六七八九十百千万两\d]+)章", title)
    if not match:
        return fallback
    raw = match.group(1)
    if raw.isdecimal():
        return int(raw)
    digits = {c: n for n, c in enumerate("零一二三四五六七八九")}
    digits.update({"〇": 0, "两": 2})
    total, part, number = 0, 0, 0
    for c in raw:
        if c in digits:
            number = digits[c]
        elif c == "万":
            total += (part + number) * 10000
            part, number = 0, 0
        else:
            part += (number or 1) * {"十": 10, "百": 100, "千": 1000}[c]
            number = 0
    return total + part + number
