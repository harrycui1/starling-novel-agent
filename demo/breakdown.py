"""拆书：从成稿里拆出「对手、交锋方式、反转、结局」四类招式，供整理招式库。

python3 breakdown.py <原文.txt> [<原文.txt> ...]，结果存在 output/breakdown/<文件名>.json。
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import run

OUT = run.ROOT / "output" / "breakdown"


def breakdown(llm, path):
    path = Path(path)
    meta, prompt = run.render("x_breakdown", {"text": path.read_text(encoding="utf-8")})
    res = llm.chat("breakdown", prompt, float(meta.get("temperature", 0.3)), True)
    out = run.parse_json(res["content"])
    record = {"book": path.name, "prompt_version": meta.get("version"), "model": res["model"],
              "seconds": res["seconds"], "usage": res["usage"], **out}
    (OUT / f"{path.stem}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return path.name, out.get("tone"), len(out.get("moves", [])), len(out.get("other", []))


def main():
    if len(sys.argv) < 2:
        sys.exit("用法：python3 breakdown.py <原文.txt> [...]")
    OUT.mkdir(parents=True, exist_ok=True)
    llm = run.LLM(run.load_env())
    with ThreadPoolExecutor(4) as pool:
        for name, tone, moves, other in pool.map(lambda p: breakdown(llm, p), sys.argv[1:]):
            print(f"{name}：{tone}，招式 {moves} 条，其他 {other} 条", flush=True)


if __name__ == "__main__":
    main()
