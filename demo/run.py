"""Starling 网文续写 Agent —— 生成段（S1～S5）演示流水线。

只依赖 Python 标准库。用法见 README.md。
每个阶段的输入、渲染后的 prompt、模型原始输出、解析结果和代码检查都存进 output/<书名>/，
展示页面由 build_viewer.py 读取这些文件生成。
"""
import argparse
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROMPTS = ROOT / "prompts"
MOVES = ROOT / "moves"
ELEMENTS = ["对手", "交锋方式", "反转", "结局"]
MOVE_RULES = {
    "library_first": "优先从招式库 moves 里选招式，写明 move_id；库里没有合适的可以自己想，move_id 留空，这样的招式会被标为 AI 新想法。",
    "library_only": "四个要素都必须从招式库 moves 里选，写明 move_id，不要自己发明招式。",
    "none": "不参考招式库，四个要素都自己设计，move_id 全部留空。",
}
STAGES = ["s1", "s2", "s3", "s4", "s5a", "s5b"]
DIMENSIONS = {"stakes", "villain_rank", "publicity", "villain_loss", "emotion_stack"}
# 常见 AI 口头禅：同一章出现 TIC_LIMIT 次及以上算用滥
TICS = ["盯着", "攥", "扫了一眼", "震了一下", "声音很轻", "看了很久", "嘴角", "眼眶", "指节发白", "深吸一口气",
        "吐出一口气", "顿了顿", "沉默了", "两秒", "三秒", "一字一顿", "没说话", "心里一沉", "倒吸一口凉气", "瞳孔",
        "喉咙发紧", "鼻子一酸", "愣了一下", "笑了笑", "一字一句"]
TIC_LIMIT = 3
RHYTHM_DEFAULT = "（节奏模板暂用通用规则；精选库拆书完成后，这里换成同题材成品稿统计出的事件节奏。）"


# ---------- 基础工具 ----------

def load_env():
    env = {}
    for path in (ROOT / ".env",):
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith(("OPENROUTER", "MODEL", "LLM_"))})
    return env


def count_words(text):
    return len(re.sub(r"\s", "", text))


def split_chapters(raw):
    heads = list(re.finditer(r"(?m)^\s*#*\s*第\s*([0-9零〇一二三四五六七八九十百]+)\s*章[^\n]*$", raw))
    if not heads:
        sys.exit("没有识别到章节标题（形如“## 第1章”）")
    title = raw[:heads[0].start()].strip().splitlines()[0] if raw[:heads[0].start()].strip() else ""
    chapters = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(raw)
        text = raw[m.end():end].strip()
        text = re.sub(r"[（(]全文完[)）]\s*$", "", text).strip()
        chapters.append({"index": i + 1, "text": text})
    return title, chapters


def dialogue_ratio(text):
    quoted = sum(count_words(q) for q in re.findall(r"“([^”]*)”", text))
    return quoted / max(count_words(text), 1)


def paragraphs(text):
    return [p.strip() for p in text.splitlines() if p.strip()]


def sentences(text):
    """按句和逗号切分并去掉引号、空白，只留 8 字以上的片段，用来查原样重复。"""
    out = []
    for s in re.split(r"[。！？!?…\n，,；;]+", text):
        s = re.sub(r"[“”‘’「」\s、：:—]", "", s)
        if len(s) >= 8:
            out.append(s)
    return out


def style_issues(text, before):
    """text 里和前文（before）或本章前面原样重复的句子，以及用滥的口头禅。"""
    seen = set(sentences(before))
    repeats = []
    for s in sentences(text):
        if s in seen and s not in repeats:
            repeats.append(s)
        seen.add(s)
    tics = {w: text.count(w) for w in TICS if text.count(w) >= TIC_LIMIT}
    return {"repeats": repeats, "tics": tics}


def style_instruction(issues):
    """把检查出的问题写成修改意见。"""
    lines = []
    if issues["repeats"]:
        lines.append("以下句子和前文原样重复，删掉或换一种写法，前面的事一句带过，不复述原话：")
        lines += [f"- {s}" for s in issues["repeats"]]
    if issues.get("over_words"):
        lines.append(f"全章压到 {issues['max_words']} 字以内（现在多了约 {issues['over_words']} 字）："
                     "删掉重复交代、感慨和可有可无的过渡，不删事件和对话里的关键信息。")
    if issues["tics"]:
        lines.append("以下词用得太多，大部分删掉或换成具体的动作和事件："
                     + "、".join(f"{w}（{n} 次）" for w, n in issues["tics"].items()))
    return "\n".join(lines)


def form_stats(text):
    paras = paragraphs(text)
    last = paras[-1] if paras else ""
    return {
        "words": count_words(text),
        "dialogue_ratio": round(dialogue_ratio(text), 3),
        "para_avg": round(statistics.mean(count_words(p) for p in paras), 1) if paras else 0,
        "last_line": last[:60],
        "ends_with_dialogue": last.endswith("”"),
    }


def render(name, values):
    raw = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    meta, body = {}, raw
    m = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
    if m:
        body = raw[m.end():]
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    for k, v in values.items():
        if not isinstance(v, str):
            v = json.dumps(v, ensure_ascii=False, indent=1)
        body = body.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{(\w+)\}\}", body)
    if left:
        raise ValueError(f"{name} 有未填的变量：{left}")
    return meta, body.strip()


def tones():
    """招式库里有的情感基调，一个基调一个文件。"""
    return [f.stem for f in sorted(MOVES.glob("*.json"))]


def load_moves(tone):
    f = MOVES / f"{tone}.json"
    return json.loads(f.read_text(encoding="utf-8"))["moves"] if f.exists() else []


def parse_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("输出里没有 JSON 对象")
    return json.loads(text[start:end + 1])


# ---------- 模型调用 ----------

class LLM:
    def __init__(self, env, dry_run=False):
        self.key = env.get("OPENROUTER_API_KEY", "")
        self.base = env.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
        self.default = env.get("MODEL", "")
        self.per_stage = {s: env.get(f"MODEL_{s.upper()}", "") for s in STAGES}
        self.reasoning = int(env.get("LLM_REASONING_TOKENS", 8000))
        self.dry_run = dry_run
        if not dry_run and (not self.key or not self.default):
            sys.exit("请在 .env 里填写 OPENROUTER_API_KEY 和 MODEL")

    def model_for(self, stage):
        return self.per_stage.get(stage) or self.default

    def chat(self, stage, prompt, temperature, json_mode, max_tokens=16000):
        model = self.model_for(stage)
        if self.dry_run:
            return {"model": model, "content": "", "usage": {}, "seconds": 0}
        # 推理模型的思考 token 也算在 max_tokens 里，单独给思考留预算，不挤占正式输出；不支持思考的模型会忽略
        body = {"model": model, "temperature": temperature, "max_tokens": max_tokens + self.reasoning,
                "reasoning": {"max_tokens": self.reasoning},
                "messages": [{"role": "user", "content": prompt}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        last = None
        for attempt in range(3):
            req = urllib.request.Request(
                self.base + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
                         "X-Title": "Starling novel agent demo"})
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=600) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"] or ""
                if not content.strip():
                    raise ValueError("模型返回空内容")
                finish = data["choices"][0].get("finish_reason")
                if finish == "length" and json_mode:
                    raise ValueError(f"输出被截断（max_tokens={body['max_tokens']}）")
                return {"model": data.get("model", model), "content": content, "finish_reason": finish,
                        "usage": data.get("usage", {}), "seconds": round(time.time() - t0, 1)}
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:500]}"
                if e.code in (400, 401, 403, 404):
                    break
                if json_mode and e.code == 422:
                    body.pop("response_format", None)
            except Exception as e:  # network errors, timeouts, bad payloads
                last = repr(e)
            time.sleep(3 * (attempt + 1))
        sys.exit(f"[{stage}] 模型调用失败：{last}")


# ---------- 流水线 ----------

class Pipeline:
    def __init__(self, args, llm):
        self.args, self.llm = args, llm
        raw = Path(args.book).read_text(encoding="utf-8")
        self.title, self.chapters = split_chapters(raw)
        self.out = Path(args.out or ROOT / "output" / Path(args.book).stem[:20])
        self.out.mkdir(parents=True, exist_ok=True)
        self.baseline = self.make_baseline()
        self.save("s0_input", {
            "stage": "S0 输入与形式基线", "book": Path(args.book).name, "title": self.title,
            "config": {"target_words": args.target, "free_chapters": args.free, "tags": args.tags or "无",
                       "direction": args.direction, "editor_note": args.note or "无",
                       "models": {s: llm.model_for(s) for s in STAGES}},
            "baseline": self.baseline})

    # 文件读写
    def path(self, name):
        return self.out / f"{name}.json"

    def save(self, name, data):
        self.path(name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def load(self, name):
        return json.loads(self.path(name).read_text(encoding="utf-8"))

    def should_run(self, stage, name):
        if self.args.only and stage != self.args.only:
            return False
        if self.args.start and STAGES.index(stage) >= STAGES.index(self.args.start):
            return True
        return not self.path(name).exists()

    def call(self, stage, prompt_name, values, json_mode=True, max_tokens=16000):
        meta, prompt = render(prompt_name, values)
        return self.ask(stage, prompt_name, meta, prompt, json_mode, max_tokens)

    def ask(self, stage, prompt_name, meta, prompt, json_mode=True, max_tokens=16000):
        temperature = float(meta.get("temperature", 0.7))
        res = self.llm.chat(stage, prompt, temperature, json_mode, max_tokens)
        record = {"prompt_name": prompt_name, "prompt_version": meta.get("version"), "model": res["model"],
                  "temperature": temperature, "prompt": prompt, "raw": res["content"],
                  "usage": res["usage"], "seconds": res["seconds"]}
        if self.llm.dry_run or not json_mode:
            return record, res["content"]
        try:
            return record, parse_json(res["content"])
        except Exception as e:
            fix = prompt + f"\n\n# 注意\n上一次输出无法解析为 JSON（{e}）。只输出一个合法的 JSON 对象。"
            res = self.llm.chat(stage, fix, temperature, json_mode, max_tokens)
            record.update(raw=res["content"], retried=str(e), seconds=record["seconds"] + res["seconds"])
            return record, parse_json(res["content"])

    # 代码算的形式基线
    def make_baseline(self):
        per = []
        for c in self.chapters:
            s = form_stats(c["text"])
            s["index"] = c["index"]
            per.append(s)
        all_text = "\n".join(c["text"] for c in self.chapters)
        first_person = all_text.count("我") / max(count_words(all_text), 1) > 0.01
        return {
            "chapters": per,
            "total_words": sum(p["words"] for p in per),
            "median_words": int(statistics.median(p["words"] for p in per)),
            "dialogue_ratio": round(dialogue_ratio(all_text), 3),
            "para_avg": round(statistics.mean(count_words(p) for p in paragraphs(all_text)), 1),
            "pov": "第一人称" if first_person else "第三人称",
        }

    def chapters_payload(self, upto=None, start=1, texts=None):
        texts = texts or {c["index"]: c["text"] for c in self.chapters}
        return [{"index": c["index"], "words": count_words(texts[c["index"]]), "text": texts[c["index"]]}
                for c in self.chapters if start <= c["index"] <= (upto or len(self.chapters))]

    # ---- S1 原文理解 ----
    def s1(self):
        rec, out = self.call("s1", "s1_understand", {
            "tags": self.args.tags or "无", "free_chapters": str(self.args.free), "tones": "、".join(tones()),
            "chapters": self.chapters_payload()})
        checks = []
        if out:
            full = "\n".join(c["text"] for c in self.chapters)
            for a in out.get("tone_anchors", []):
                ok = a.get("quote", "") and a["quote"] in full
                checks.append({"name": f"语气锚点逐字出自原文：{a.get('quote', '')[:20]}", "pass": bool(ok)})
            door = out.get("door_closed_after", {}).get("chapter", 0)
            checks.append({"name": f"主线收完的章在原作范围内（第 {door} 章）", "pass": 1 <= door <= len(self.chapters)})
            evs = [len(c.get("small_events", [])) for c in out.get("event_structure", {}).get("chapters", [])]
            out["derived"] = {"events_per_chapter": round(statistics.mean(evs), 2) if evs else 0,
                              "events_by_chapter": evs}
            checks.append({"name": f"逐章事件覆盖全部 {len(self.chapters)} 章", "pass": len(evs) == len(self.chapters)})
        # 演练结果另存，否则正式运行会把它当成已完成的 S1 跳过
        name = "s1_understand.dryrun" if self.llm.dry_run else "s1_understand"
        self.save(name, {"stage": "S1 原文理解", **rec, "output": out, "checks": checks})

    # ---- S2 方向生成 ----
    def s2_values(self):
        u = self.load("s1_understand")["output"]
        return {
            "target_words": str(self.args.target), "total_words": str(self.baseline["total_words"]),
            "chapter_words": {c["index"]: c["words"] for c in self.baseline["chapters"]},
            "free_chapters": str(self.args.free), "editor_note": self.args.note or "无",
            "references": "暂无（精选库参考稿待接入）",
            "moves": self.moves_for_prompt(u), "move_rule": MOVE_RULES[self.move_mode],
            "understanding": {k: v for k, v in u.items() if k != "derived"},
            "chapters": self.chapters_payload()}

    @property
    def move_mode(self):
        return getattr(self.args, "move_mode", "library_first")

    def moves_for_prompt(self, u):
        if self.move_mode == "none":
            return "（本次不用招式库）"
        moves = load_moves(u.get("genre_contract", {}).get("tone", ""))
        return [{k: m.get(k) for k in ("id", "element", "name", "how", "premise", "setup", "taboo")} for m in moves] \
            or "（这个情感基调还没有招式库，自己设计）"

    def element_checks(self, d):
        tag = d.get("strategy", "?")
        el = d.get("elements") or {}
        ids = {m["id"] for m in load_moves(self.load("s1_understand")["output"].get("genre_contract", {}).get("tone", ""))}
        used = [e.get("move_id") for e in el.values() if e.get("move_id")]
        checks = [{"name": f"[{tag}] 四个要素都写了", "pass": all(el.get(k, {}).get("name") for k in ELEMENTS)},
                  {"name": f"[{tag}] 引用的招式都在库里", "pass": all(i in ids for i in used)}]
        if self.move_mode == "library_only":
            checks.append({"name": f"[{tag}] 四个要素都来自招式库", "pass": len(used) == len(ELEMENTS)})
        return checks

    @staticmethod
    def element_key(e):
        return e.get("move_id") or e.get("name", "")

    def diversity_checks(self, dirs):
        """三个方向两两之间至少两个要素不同。"""
        checks = []
        for i, a in enumerate(dirs):
            for b in dirs[i + 1:]:
                ea, eb = a.get("elements") or {}, b.get("elements") or {}
                diff = [k for k in ELEMENTS if self.element_key(ea.get(k, {})) != self.element_key(eb.get(k, {}))]
                checks.append({"name": f"[{a.get('strategy')}/{b.get('strategy')}] 不同的要素 {len(diff)} 个（{'、'.join(diff) or '无'}）",
                               "pass": len(diff) >= 2})
        return checks

    def direction_checks(self, d):
        """算保留比例（写回 d），返回这个方向的代码检查。"""
        u = self.load("s1_understand")["output"]
        words = {c["index"]: c["words"] for c in self.baseline["chapters"]}
        door = u.get("door_closed_after", {}).get("chapter", len(self.chapters))
        pots = {p["id"]: p for p in u.get("potentials", [])}
        tag = d.get("strategy", "?")
        cut = int(d.get("cut_after_chapter", 0))
        kept = sum(w for i, w in words.items() if i <= cut) / self.baseline["total_words"]
        d["kept_ratio"] = round(kept, 3)
        deleted = [h["id"] for h in u.get("highlights", []) if h.get("chapter", 0) > cut]
        covered = {x.get("highlight_id") for x in d.get("highlight_ledger", [])}
        pot = pots.get(d.get("potential_used"), {})
        return [
            {"name": f"[{tag}] 保留到的章不晚于主线收完的章（第 {cut} 章 ≤ 第 {door} 章）", "pass": 0 < cut <= door},
            {"name": f"[{tag}] 保留原文 ≥ 60%（{kept:.0%}）", "pass": kept >= 0.6},
            {"name": f"[{tag}] 被删的原作高光都写了处理办法 {deleted}", "pass": set(deleted) <= covered},
            {"name": f"[{tag}] 加码条目都写了维度",
             "pass": all(x.get("dimensions") and set(x["dimensions"]) <= DIMENSIONS
                         for x in d.get("highlight_ledger", []) if x.get("treatment") == "amplify")},
            {"name": f"[{tag}] 新冲突用的线索 {d.get('potential_used')} 存在且强度 ≥ 3",
             "pass": bool(pot) and pot.get("strength", 0) >= 3},
            {"name": f"[{tag}] 伏笔只补在免费章之后、保留的章之内",
             "pass": all(self.args.free < int(b.get("chapter", 0)) <= cut
                         for b in d.get("foreshadow_backfill", []))},
            {"name": f"[{tag}] 新人物都来自某条线索",
             "pass": all(n.get("potential_id") in pots for n in d.get("new_characters", []))},
        ]

    def s2(self):
        rec, out = self.call("s2", "s2_directions", self.s2_values())
        checks = []
        dirs = (out or {}).get("directions", [])
        for d in dirs:
            checks += self.direction_checks(d) + self.element_checks(d)
        checks += self.diversity_checks(dirs)
        self.save("s2_directions", {"stage": "S2 方向生成", **rec, "output": out, "checks": checks})

    def custom_direction(self, idea):
        """按编辑的想法补全成一个方向，strategy 为 custom，替换掉之前的自定义方向。"""
        meta, base = render("s2_directions", self.s2_values())
        _, extra = render("s2_custom", {"idea": idea})
        rec, out = self.ask("s2", "s2_directions+s2_custom", meta, base + "\n\n" + extra)
        d = out["directions"][0]
        d["strategy"] = "custom"
        data = self.load("s2_directions")
        data["output"]["directions"] = [x for x in data["output"]["directions"] if x.get("strategy") != "custom"] + [d]
        data["checks"] = [c for c in data["checks"] if not c["name"].startswith("[custom]")] \
            + self.direction_checks(d) + self.element_checks(d)
        data["custom"] = {"idea": idea, **rec}
        self.save("s2_directions", data)
        return d

    def auto_select(self):
        """让模型从已有方向里选一个，返回 (strategy, reason, 调用记录)。"""
        u = self.load("s1_understand")["output"]
        dirs = self.load("s2_directions")["output"]["directions"]
        rec, out = self.call("s2", "s2_select", {
            "editor_note": self.args.note or "无",
            "understanding": {k: u.get(k) for k in ("genre_contract", "highlights", "potentials")},
            "directions": dirs})
        strategy = out.get("strategy")
        if strategy not in {d.get("strategy") for d in dirs}:
            strategy = dirs[0].get("strategy")
        return strategy, out.get("reason", ""), rec

    # ---- 编辑介入①：选方向（演示中按默认规则自动选） ----
    def gate1(self):
        dirs = self.load("s2_directions")["output"]["directions"]
        chosen = next((d for d in dirs if d.get("strategy") == self.args.direction), dirs[0])
        self.save("gate1", {"stage": "编辑介入① 选方向", "mode": "演示：按默认规则自动选择",
                            "rule": f"默认选 {self.args.direction}，没有则选第一个",
                            "selected": chosen.get("strategy"), "editor_note": self.args.note or "无",
                            "reject_reasons_options": ["类型跑偏", "切点不对", "新冲突生硬", "不够爽",
                                                       "高光降级", "原文理解有误"]})
        return chosen

    def plan(self):
        d = self.load("gate1")
        dirs = self.load("s2_directions")["output"]["directions"]
        direction = next(x for x in dirs if x.get("strategy") == d["selected"])
        cut = int(direction["cut_after_chapter"])
        n = max(8, round(self.args.target / self.baseline["median_words"]))
        return direction, cut, cut + 1, cut + n, n

    def understanding_brief(self):
        u = self.load("s1_understand")["output"]
        return {k: u.get(k) for k in ("genre_contract", "characters", "highlights", "potentials", "low_points")}

    # ---- S3 大纲 ----
    def s3(self):
        direction, cut, first, last, n = self.plan()
        u = self.load("s1_understand")["output"]
        kept_events = [c for c in u["event_structure"]["chapters"] if c["index"] <= cut]
        epc = u.get("derived", {}).get("events_per_chapter", 1.5)
        rec, out = self.call("s3", "s3_outline", {
            "first_chapter": str(first), "last_chapter": str(last), "n_chapters": str(n),
            "median_words": str(self.baseline["median_words"]), "events_per_chapter": str(epc),
            "reveal_deadline": str(first + max(2, n // 4)), "rhythm_template": RHYTHM_DEFAULT,
            "direction": direction, "editor_note": self.args.note or "无",
            "understanding": self.understanding_brief(), "kept_events": kept_events})
        checks = []
        if out:
            span = set()
            for b in out.get("big_events", []):
                a, z = b.get("chapters", [0, 0])[0], b.get("chapters", [0, 0])[-1]
                span |= set(range(int(a), int(z) + 1))
            checks.append({"name": f"大事件覆盖第 {first}～{last} 章，没有空章",
                           "pass": set(range(first, last + 1)) <= span})
            placed = {x.get("highlight_id") for x in out.get("highlight_placements", [])}
            need = {x.get("highlight_id") for x in direction.get("highlight_ledger", [])}
            checks.append({"name": f"被删高光都排进了某一章 {sorted(need)}", "pass": need <= placed})
            r = int(out.get("second_conflict_reveal_chapter", 0))
            checks.append({"name": f"第二冲突在第 {first + max(2, n // 4)} 章之前亮出（第 {r} 章）",
                           "pass": first <= r <= first + max(2, n // 4)})
        self.save("s3_outline", {"stage": "S3 大纲生成", **rec, "output": out, "checks": checks,
                                 "plan": {"cut_after_chapter": cut, "first": first, "last": last, "n_chapters": n}})

    # ---- S4 细纲 ----
    def s4(self):
        direction, cut, first, last, n = self.plan()
        u = self.load("s1_understand")["output"]
        epc = u.get("derived", {}).get("events_per_chapter", 1.5)
        lo, hi = max(1, math.floor(epc)), math.ceil(epc) + 1
        outline = self.load("s3_outline")["output"]
        rec, out = self.call("s4", "s4_detail", {
            "first_chapter": str(first), "last_chapter": str(last), "n_chapters": str(n),
            "median_words": str(self.baseline["median_words"]), "events_per_chapter": str(epc),
            "dialogue_ratio": f"{self.baseline['dialogue_ratio']:.0%}", "event_min": str(lo), "event_max": str(hi),
            "outline": outline, "direction": direction,
            "understanding": {"genre_contract": u["genre_contract"], "characters": u["characters"]}},
            max_tokens=24000)
        checks = self.detail_checks(out.get("chapters", [])) if out else []
        self.save("s4_detail", {"stage": "S4 细纲生成", **rec, "output": out, "checks": checks})
        self.save("gate2", {"stage": "编辑介入② 确认细纲", "mode": "演示：自动确认",
                            "note": "真实流程中编辑在这里逐章确认或批改，方向和人设问题在此拦下"})

    def detail_checks(self, chapters):
        _, _, first, last, _ = self.plan()
        epc = self.load("s1_understand")["output"].get("derived", {}).get("events_per_chapter", 1.5)
        lo, hi = max(1, math.floor(epc)), math.ceil(epc) + 1
        idx = [int(c.get("index", 0)) for c in chapters]
        checks = [{"name": f"细纲覆盖第 {first}～{last} 章", "pass": idx == list(range(first, last + 1))}]
        for c in chapters:
            k = len(c.get("events", []))
            hook = c.get("ending_hook", {})
            checks.append({"name": f"第 {c.get('index')} 章：事件数 {k}（{lo}～{hi}），钩子落在 {hook.get('type')}",
                           "pass": lo <= k <= hi and hook.get("type") in ("event", "dialogue")
                           and bool(hook.get("content"))})
        return checks

    # ---- S5a 伏笔回填 ----
    def s5a(self):
        direction, cut, *_ = self.plan()
        items = direction.get("foreshadow_backfill", [])
        texts = {c["index"]: c["text"] for c in self.chapters}
        rec, out, applied = {}, {"insertions": []}, []
        if items:
            start = self.args.free + 1
            rec, out = self.call("s5a", "s5a_backfill", {
                "backfill": items, "chapters": self.chapters_payload(upto=cut, start=start)})
            for ins in out.get("insertions", []) if out else []:
                ch, anchor, add = int(ins.get("chapter", 0)), ins.get("anchor", ""), ins.get("insert_text", "")
                ok = self.args.free < ch <= cut and anchor and texts.get(ch, "").count(anchor) == 1
                if ok:
                    texts[ch] = texts[ch].replace(anchor, anchor + "\n" + add, 1)
                applied.append({"chapter": ch, "anchor": anchor, "insert_text": add, "applied": bool(ok)})
        kept = {i: t for i, t in texts.items() if i <= cut}
        checks = [{"name": f"插入：第 {a['chapter']} 章 “{a['anchor'][:16]}…”", "pass": a["applied"]} for a in applied]
        self.save("s5a_backfill", {"stage": "S5a 伏笔回填", **rec, "output": out, "applied": applied,
                                   "checks": checks, "kept_text": kept,
                                   "skipped": "" if items else "选定方向没有需要回填的伏笔"})

    # ---- S5b 逐章正文 ----
    def chapter_file(self, i):
        return self.out / "s5b" / f"ch{i:02d}.json"

    def written_chapters(self):
        """已写的续章 {章号: 正文}，按文件读取，编辑改过的版本也在这里。"""
        d = self.out / "s5b"
        return {int(f.stem[2:]): json.loads(f.read_text(encoding="utf-8"))["text"]
                for f in sorted(d.glob("ch*.json"))} if d.exists() else {}

    def before_text(self, i):
        """第 i 章之前的全部文字：保留的原文（含伏笔）+ 已写的续章。"""
        kept = self.load("s5a_backfill")["kept_text"]
        written = self.written_chapters()
        return "\n".join([v for _, v in sorted((int(k), v) for k, v in kept.items())]
                         + [written[k] for k in sorted(written) if k < i])

    def overused(self, i):
        """前面续章里平均每章用到一次以上的口头禅，写第 i 章时提醒模型避开。"""
        prev = [t for k, t in self.written_chapters().items() if k < i]
        if not prev:
            return "（无）"
        counts = {w: sum(t.count(w) for t in prev) for w in TICS}
        hot = [f"{w}（已用 {n} 次）" for w, n in sorted(counts.items(), key=lambda x: -x[1]) if n >= max(2, len(prev))]
        return "、".join(hot) or "（无）"

    def chapter_checks(self, text, i):
        b = self.baseline
        stats = form_stats(text)
        issues = style_issues(text, self.before_text(i))
        limit = int(b["median_words"] * 1.5)
        if stats["words"] > limit:
            issues.update(over_words=stats["words"] - limit, max_words=limit)
        stats["style"] = issues
        checks = [
            {"name": f"字数 {stats['words']}（原文中位数 {b['median_words']}，"
                     f"范围 {int(b['median_words'] * 0.7)}～{int(b['median_words'] * 1.5)}）",
             "pass": b["median_words"] * 0.7 <= stats["words"] <= b["median_words"] * 1.5},
            {"name": f"对话占比 {stats['dialogue_ratio']:.0%}（原文 {b['dialogue_ratio']:.0%}）",
             "pass": abs(stats["dialogue_ratio"] - b["dialogue_ratio"]) <= 0.10},
            {"name": f"段落平均 {stats['para_avg']} 字（原文 {b['para_avg']}）",
             "pass": 0.7 <= stats["para_avg"] / max(b["para_avg"], 1) <= 1.4},
            {"name": f"和前文原样重复的句子 {len(issues['repeats'])} 句", "pass": not issues["repeats"]},
            {"name": "口头禅：" + ("、".join(f"{w}×{n}" for w, n in issues["tics"].items()) or f"没有用到 {TIC_LIMIT} 次以上的"),
             "pass": not issues["tics"]},
        ]
        return stats, checks

    def write_chapter(self, i, auto_revise=False, prompt_name="s5b_write", target=None):
        """写第 i 章。前文取第 i 章之前已写的续章（含编辑改过的）。auto_revise 时检查不过自动改一次。
        target 给定时写到这个文件（多模型对比的候选稿），不动正式的章节文件。"""
        direction, cut, first, last, n = self.plan()
        u = self.load("s1_understand")["output"]
        detail = self.load("s4_detail")["output"]["chapters"]
        c = next(x for x in detail if int(x["index"]) == i)
        kept = {int(k): v for k, v in self.load("s5a_backfill")["kept_text"].items()}
        kept_text = "\n\n".join(f"## 第{k}章\n{t}" for k, t in sorted(kept.items()))
        anchors = "\n".join(f"   - {a['quote']}" for a in u.get("tone_anchors", []))
        gc = u["genre_contract"]
        b = self.baseline
        written = {k: v for k, v in self.written_chapters().items() if k < i}
        nxt = next((x for x in detail if int(x["index"]) == i + 1), "（本章为最后一章）")
        rec, text = self.call("s5b", prompt_name, {
            "chapter_index": str(i), "n_chapters": str(n), "position": str(i - first + 1),
            "median_words": str(b["median_words"]), "min_words": str(int(b["median_words"] * 0.7)),
            "max_words": str(int(b["median_words"] * 1.5)),
            "dialogue_ratio": f"{b['dialogue_ratio']:.0%}", "para_len": str(b["para_avg"]), "pov": b["pov"],
            "tone_anchors": anchors, "core_emotion": gc.get("core_emotion", ""),
            "forbidden_drifts": "；".join(gc.get("forbidden_drifts", [])),
            "kept_text": kept_text, "carried_facts": direction.get("carried_facts", []) or "无",
            "written_text": "\n\n".join(f"## 第{k}章\n{v}" for k, v in sorted(written.items())) or "（尚无）",
            "characters": u.get("characters", []), "chapter_outline": c, "next_outline": nxt,
            "overused": self.overused(i)},
            json_mode=False, max_tokens=6000)
        text = self.clean(text)
        stats, checks = self.chapter_checks(text, i)
        data = {"stage": f"S5b 正文 第{i}章", **rec, "text": text, "stats": stats, "outline": c, "checks": checks}
        # 有重复句、口头禅或超字数，按检查结果自动改一次；直出稿留在 draft 里
        if auto_revise and (stats["style"]["repeats"] or stats["style"]["tics"] or stats["style"].get("over_words")):
            instruction = style_instruction(stats["style"])
            rec2, revised = self.revise(c, text, instruction)
            stats, checks = self.chapter_checks(revised, i)
            data.update(draft={"text": text, "checks": data["checks"]}, text=revised, stats=stats, checks=checks,
                        revision={"instruction": instruction, "auto": True, **rec2},
                        seconds=round(rec["seconds"] + rec2["seconds"], 1))
        target = Path(target) if target else self.chapter_file(i)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return stats, data

    def revise(self, outline, text, instruction):
        rec, out = self.call("s5b", "s5c_revise", {"instruction": instruction, "chapter_outline": outline,
                                                    "text": text}, json_mode=False, max_tokens=6000)
        return rec, self.clean(out)

    def revise_chapter(self, i, instruction):
        """编辑按意见修改第 i 章；改之前的版本留在 previous，可以恢复。"""
        f = self.chapter_file(i)
        data = json.loads(f.read_text(encoding="utf-8"))
        rec, revised = self.revise(data["outline"], data["text"], instruction)
        stats, checks = self.chapter_checks(revised, i)
        data.update(previous={"text": data["text"], "stats": data["stats"], "checks": data["checks"]},
                    text=revised, stats=stats, checks=checks, revision={"instruction": instruction, "auto": False, **rec})
        f.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def restore_chapter(self, i):
        f = self.chapter_file(i)
        data = json.loads(f.read_text(encoding="utf-8"))
        prev = data.pop("previous", None)
        if prev:
            data.update(prev)
            data.pop("revision", None)
            data.pop("adopted_from", None)
            f.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def save_chapter_edit(self, i, text):
        f = self.chapter_file(i)
        data = json.loads(f.read_text(encoding="utf-8"))
        data["stats"], data["checks"] = self.chapter_checks(text, i)
        data.update(text=text, edited=True)
        f.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def write_manuscript(self):
        kept = {int(k): v for k, v in self.load("s5a_backfill")["kept_text"].items()}
        full = [f"{self.title}\n"] + [f"## 第{i}章\n{t}\n" for i, t in sorted(kept.items())]
        full += [f"## 第{i}章\n{t}\n" for i, t in sorted(self.written_chapters().items())]
        (self.out / "manuscript.txt").write_text("\n".join(full), encoding="utf-8")

    def s5b(self):
        direction, cut, first, last, n = self.plan()
        limit = last if not self.args.max_chapters else min(last, first + self.args.max_chapters - 1)
        for i in range(first, limit + 1):
            if self.chapter_file(i).exists() and not (self.args.start == "s5b" and self.args.rewrite):
                continue
            stats, data = self.write_chapter(i, self.args.auto_revise)
            print(f"  第 {i} 章完成：{stats['words']} 字，{data['seconds']} 秒", flush=True)
        self.write_manuscript()

    @staticmethod
    def clean(text):
        lines = [l for l in text.strip().splitlines()
                 if not re.match(r"^\s*(#+\s*)?第\s*[0-9一二三四五六七八九十百]+\s*章", l)
                 and not re.match(r"^\s*(```|以下是|字数|（本章|\(本章)", l)]
        return "\n".join(lines).strip()

    def run(self):
        steps = [("s1", "s1_understand", self.s1), ("s2", "s2_directions", self.s2),
                 ("s3", "s3_outline", self.s3), ("s4", "s4_detail", self.s4),
                 ("s5a", "s5a_backfill", self.s5a), ("s5b", "manuscript", self.s5b)]
        for stage, name, fn in steps:
            if stage == "s5b":
                run = self.args.only in (None, "s5b")
            else:
                run = self.should_run(stage, name)
            if not run:
                print(f"[{stage}] 已有结果，跳过")
                if stage == "s2" and not self.path("gate1").exists():
                    self.gate1()
                continue
            print(f"[{stage}] 运行中……", flush=True)
            fn()
            if self.llm.dry_run:
                print(f"[{stage}] 演练模式：已渲染 prompt，停止")
                return
            if stage == "s2":
                self.gate1()
        print(f"完成，结果在 {self.out}")


def main():
    p = argparse.ArgumentParser(description="Starling 网文续写生成段演示")
    p.add_argument("book", help="原文 txt，章节标题形如“## 第1章”")
    p.add_argument("--out", help="输出目录，默认 output/<书名>")
    p.add_argument("--target", type=int, default=20000, help="续写目标字数")
    p.add_argument("--free", type=int, default=4, help="免费章数，伏笔只能补在这之后")
    p.add_argument("--tags", default="", help="文纲标签：题材、核心套路")
    p.add_argument("--note", default="", help="编辑补充要求")
    p.add_argument("--direction", default="A", help="演示中编辑介入①自动选择的方向编号，没有则选第一个")
    p.add_argument("--moves", dest="move_mode", default="library_first", choices=list(MOVE_RULES),
                   help="方向生成用招式库的方式：库优先 / 只用库 / 不用库")
    p.add_argument("--start", choices=STAGES, help="从某个阶段起强制重跑")
    p.add_argument("--only", choices=STAGES, help="只跑某个阶段")
    p.add_argument("--rewrite", action="store_true", help="配合 --start s5b，重写已写的章节")
    p.add_argument("--auto-revise", action="store_true", help="正文检查不过时自动按检查结果改一次（默认直出）")
    p.add_argument("--max-chapters", type=int, default=0, help="正文只写前 N 章（0 为全部）")
    p.add_argument("--dry-run", action="store_true", help="只渲染 S1 的 prompt，不调用模型")
    args = p.parse_args()
    Pipeline(args, LLM(load_env(), args.dry_run)).run()


if __name__ == "__main__":
    main()
