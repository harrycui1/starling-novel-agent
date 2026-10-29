"""把 run.py 的输出目录做成一个可离线打开的展示页面：python build_viewer.py output/<书名>"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else sys.exit("用法：python build_viewer.py output/<书名>")
    data = {}
    for name in ("s0_input", "s1_understand", "s2_directions", "gate1", "s3_outline", "s4_detail", "gate2",
                 "s5a_backfill"):
        p = out / f"{name}.json"
        if p.exists():
            data[name] = json.loads(p.read_text(encoding="utf-8"))
    data["s5b"] = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((out / "s5b").glob("ch*.json"))] \
        if (out / "s5b").exists() else []
    template = (ROOT / "viewer_template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = template.replace("/*__DATA__*/null", payload)
    target = out / "demo.html"
    target.write_text(html, encoding="utf-8")
    print(f"已生成 {target}")


if __name__ == "__main__":
    main()
