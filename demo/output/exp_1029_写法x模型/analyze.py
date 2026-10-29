"""汇总对照实验：python3 analyze.py <demo 目录> <项目目录> <输出目录>"""
import json
import sys
from collections import defaultdict
from pathlib import Path

DEMO, PROJ, OUT = map(Path, sys.argv[1:4])
sys.path.insert(0, str(DEMO))
import run  # noqa: E402

data = json.loads((OUT / "results.json").read_text(encoding="utf-8"))
orig = (PROJ / "source.txt").read_text(encoding="utf-8")
orig_len = run.count_words(orig)
# 原作完全不用的口头禅 = 典型 AI 腔；原作也用的，只看是否明显高于原作
ai_only = [w for w in run.TICS if orig.count(w) == 0]
shared = [w for w in run.TICS if orig.count(w) > 0]
orig_shared_rate = sum(orig.count(w) for w in shared) / orig_len * 1000

rows = defaultdict(list)
for r in data["results"]:
    rows[(r["model"], r["variant"])].append(r)
# 同一模型同一写法的另一次采样：项目里现有的纯直出（flash + A）
for i in data["chapters"]:
    t = json.loads((PROJ / "s5b" / f"ch{i:02d}.json").read_text(encoding="utf-8"))
    rows[("deepseek/deepseek-v4.1-flash", "A′现有直出")].append(
        {"chapter": i, "text": t["text"], "stats": t["stats"], "seconds": t["seconds"], "cost": t.get("usage", {}).get("cost")})

print(f"原作也用的口头禅：{shared}（原作每千字 {orig_shared_rate:.2f}）")
print(f"原作不用的口头禅：{len(ai_only)} 个\n")
head = "模型 | 写法 | 完成 | 重复句 | AI腔/千字 | 共用词/千字 | 每章字数 | 超上限章 | 对话 | 段落 | 秒/章 | $/章"
print(head)
summary = []
for (m, v), rs in sorted(rows.items(), key=lambda x: (x[0][0], x[0][1])):
    ok = [r for r in rs if "text" in r]
    if not ok:
        print(f"{m} | {v} | 0/{len(rs)} | 全部失败：{rs[0].get('error', '')[:80]}")
        continue
    text = "".join(r["text"] for r in ok)
    n = run.count_words(text)
    rep = sum(len(r["stats"]["style"]["repeats"]) for r in ok)
    ai = sum(text.count(w) for w in ai_only) / n * 1000
    sh = sum(text.count(w) for w in shared) / n * 1000
    words = [r["stats"]["words"] for r in ok]
    over = sum(w > 1516 for w in words)
    dia = run.dialogue_ratio(text)
    para = sum(r["stats"]["para_avg"] for r in ok) / len(ok)
    sec = sum(r["seconds"] for r in ok) / len(ok)
    costs = [r["cost"] for r in ok if r.get("cost") is not None]
    cost = sum(costs) / len(costs) if costs else float("nan")
    row = dict(model=m, variant=v, done=f"{len(ok)}/{len(rs)}", repeats=rep, ai=round(ai, 2), shared=round(sh, 2),
               words=round(sum(words) / len(words)), over=over, dialogue=round(dia, 2), para=round(para, 1),
               sec=round(sec), cost=round(cost, 4))
    summary.append(row)
    print(" | ".join(str(x) for x in row.values()))
(OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
print("\n原作：对话 22%，段落 18.7 字，每章中位 1011 字（上限 1516）")
