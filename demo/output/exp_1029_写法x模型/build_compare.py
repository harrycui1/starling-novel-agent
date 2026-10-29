"""把对照实验结果做成并排阅读页：python3 build_compare.py（在本目录运行），生成 对比.html"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEMO = HERE.parent.parent
sys.path.insert(0, str(DEMO))
import run  # noqa: E402

data = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
proj = DEMO / "output" / "wb_1028-2242-649b"
orig = (proj / "source.txt").read_text(encoding="utf-8")
detail = {int(c["index"]): c for c in json.loads((proj / "s4_detail.json").read_text(encoding="utf-8"))["output"]["chapters"]}
payload = {
    "chapters": data["chapters"],
    "outline": {i: {"title": detail[i]["title"], "conflict": detail[i]["core_conflict"],
                    "hook": detail[i]["ending_hook"]["content"]} for i in data["chapters"]},
    "ai_only": [w for w in run.TICS if orig.count(w) == 0],
    "baseline": {"median": 1011, "dialogue": 0.22},
    "results": [{k: r.get(k) for k in ("model", "variant", "chapter", "text")} | {
        "words": r["stats"]["words"], "dialogue": r["stats"]["dialogue_ratio"],
        "repeats": r["stats"]["style"]["repeats"]} for r in data["results"] if "text" in r],
}
html = (HERE / "compare_template.html").read_text(encoding="utf-8").replace(
    "/*__DATA__*/null", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
(HERE / "对比.html").write_text(html, encoding="utf-8")
print("已生成", HERE / "对比.html")
