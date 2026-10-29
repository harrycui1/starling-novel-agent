"""正文写法 × 模型对照实验。

固定：同一本书、同一方向和细纲，每章的前文都用项目里现有的纯直出版本（s5b/）。
变量：模型（3 个）× 写法（A 现状 / B 规则挪到末尾 / C 末尾 + 原作段落示范、去掉禁用词）。
用法：python3 run_exp.py <demo 目录> <项目目录> <输出目录>
"""
import json
import re
import shutil
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DEMO, PROJ, OUT = map(Path, sys.argv[1:4])
sys.path.insert(0, str(DEMO))
import run  # noqa: E402

MODELS = ["deepseek/deepseek-v4.1-flash", "openai/gpt-6.1-sol", "google/gemini-4-argon"]
OUT.mkdir(parents=True, exist_ok=True)

# ---- 三种写法的 prompt ----
src = (DEMO / "prompts" / "s5b_write.md").read_text(encoding="utf-8")
rules = src[src.index("# 写法要求"):src.index("# 输入资料")]
body_wo_rules = src.replace(rules, "")
tail = body_wo_rules.index("# 输出")
prompt_b = body_wo_rules[:tail] + rules + body_wo_rules[tail:]

# C：原作里语气锚点所在的段落（前后各 3 行）作为示范；去掉神态词禁令和「已用滥的词」
kept = {int(k): v for k, v in json.loads((PROJ / "s5a_backfill.json").read_text(encoding="utf-8"))["kept_text"].items()}
anchors = json.loads((PROJ / "s1_understand.json").read_text(encoding="utf-8"))["output"]["tone_anchors"]
lines = [l for i in sorted(kept) for l in run.paragraphs(kept[i])]
samples = []
for a in anchors:
    hit = next((n for n, l in enumerate(lines) if a["quote"][:12] in l), None)
    if hit is not None:
        seg = "\n".join(lines[max(0, hit - 3): hit + 4])
        if seg not in samples:
            samples.append(seg)
    if len(samples) == 3:
        break
rules_c = re.sub(r"   - 用神态小动作代替情节：[^\n]*\n", "", rules)
rules_c = re.sub(r"9\. 前面章节已经用得太多的词[^\n]*\n", "", rules_c)
rules_c += ("9. 情绪和压力照下面几段原作的写法来写：靠事件、对话和具体的动作推出来，"
            "人物不做多余的神态和小动作。只学写法，不要照抄句子。\n\n"
            + "\n\n".join(f"【原作示范 {k + 1}】\n{s}" for k, s in enumerate(samples)) + "\n\n")
prompt_c = body_wo_rules[:tail] + rules_c + body_wo_rules[tail:]

pdir = OUT / "prompts"
shutil.copytree(DEMO / "prompts", pdir, dirs_exist_ok=True)
(pdir / "exp_A.md").write_text(src, encoding="utf-8")
(pdir / "exp_B.md").write_text(prompt_b, encoding="utf-8")
(pdir / "exp_C.md").write_text(prompt_c, encoding="utf-8")
run.PROMPTS = pdir

# ---- 选重复最多的 4 章 ----
args = types.SimpleNamespace(book=str(PROJ / "source.txt"), out=str(PROJ), target=20000, free=4, tags="", note="",
                             direction="steady", start=None, only=None, rewrite=False, max_chapters=0, auto_revise=False)
base = run.Pipeline(args, run.LLM(run.load_env(), dry_run=True))
W = base.written_chapters()
rep = {i: len(run.style_issues(W[i], base.before_text(i))["repeats"]) for i in W}
chapters = sorted(sorted(rep, key=lambda i: -rep[i])[:4])
print("选的章节（现状直出的重复句数）：", {i: rep[i] for i in chapters}, flush=True)


def job(model, variant, i):
    d = OUT / "runs" / f"{model.split('/')[1]}_{variant}_ch{i:02d}"
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(PROJ, d, ignore=shutil.ignore_patterns("s5b_v*", "manuscript*", "demo.html"))
    a = types.SimpleNamespace(**{**vars(args), "out": str(d), "book": str(d / "source.txt")})
    llm = run.LLM(run.load_env())
    llm.per_stage["s5b"] = model
    p = run.Pipeline(a, llm)
    try:
        p.write_chapter(i, False, f"exp_{variant}")
        r = json.loads(p.chapter_file(i).read_text(encoding="utf-8"))
        print(f"  完成 {model} {variant} 第{i}章 {r['stats']['words']}字 {r['seconds']}秒", flush=True)
        return {"model": model, "variant": variant, "chapter": i, "text": r["text"], "stats": r["stats"],
                "seconds": r["seconds"], "cost": r.get("usage", {}).get("cost"), "returned_model": r["model"]}
    except BaseException as e:  # run.LLM 失败时 sys.exit
        print(f"  失败 {model} {variant} 第{i}章：{e}", flush=True)
        return {"model": model, "variant": variant, "chapter": i, "error": str(e)}


jobs = [(m, v, i) for m in MODELS for v in "ABC" for i in chapters]
with ThreadPoolExecutor(max_workers=12) as ex:
    results = list(ex.map(lambda x: job(*x), jobs))
(OUT / "results.json").write_text(json.dumps({"chapters": chapters, "results": results}, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
print("全部完成", flush=True)
