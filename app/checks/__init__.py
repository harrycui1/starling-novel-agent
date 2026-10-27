import math
import re

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


def chapter_count(target, channel):
    return max(settings.min_chapters, min(settings.max_chapters, math.floor(target / settings.channels[channel]["chapter_words"] + .5)))


def normalize(text):
    return re.sub(r"[\W_]", "", text)


def similarity(a, b):
    grams = lambda s: {s[i:i + 3] for i in range(max(1, len(s) - 2))}
    x, y = grams(normalize(a)), grams(normalize(b))
    return len(x & y) / max(len(x | y), 1)


def clean_draft(text, index, title):
    lines = text.strip().splitlines()
    lines = [line for line in lines if not re.match(r"^(?:以下是|字数统计|本章共|【(?:分析|自检)|```)", line.strip())]
    if lines and re.match(r"^第.+章", lines[0]):
        lines.pop(0)
    return f"第{index}章 {title}\n\n" + "\n".join(lines).strip()


def draft_issues(text, plan):
    issues = []
    body = text.partition("\n")[2]
    def add(code, detail):
        issues.append({"code": code, "detail": detail, "verdict": "info"})
    if abs(count_words(body) - plan.target_words) > plan.target_words * settings.word_tolerance:
        add("length", f"正文{count_words(body)}字，目标{plan.target_words}字")
    last = "\n".join([p for p in body.splitlines() if p.strip()][-3:])
    for phrase in settings.banned_endings_file.read_text().splitlines():
        if phrase and phrase in last:
            add("ending", f"结尾禁用表达：{phrase}")
    for phrase in settings.banned_words_file.read_text().splitlines():
        if phrase and body.count(phrase) > settings.banned_word_threshold:
            add("phrase", f"高频词：{phrase}")
    return issues


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
