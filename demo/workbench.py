"""网文续写工作台：python3 workbench.py，浏览器打开 http://127.0.0.1:8765

只依赖 Python 标准库。复用 run.py 的流水线，每个项目存在 output/wb_<id>/，结构和 run.py 的输出一致。
流程：上传 → 选方向（原文理解和三个方向在后台生成）→ 确认细纲（大纲在后台生成）→ 逐章写正文 → 导出。
"""
import json
import os
import re
import secrets
import shutil
import threading
import time
import traceback
import types
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import run

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
HOST, PORT = "127.0.0.1", int(os.environ.get("PORT", 8765))
MODEL_STAGES = {"s1": "原文理解", "s2": "方向生成与选择", "s3": "大纲", "s4": "细纲", "s5a": "伏笔回填", "s5b": "正文"}
STEPS = ["upload", "directions", "detail", "writing", "done"]
COMPARE_MODELS = ["deepseek/deepseek-v4.1-flash", "google/gemini-4-argon", "openai/gpt-6.1-sol"]
# 某一步重做时要清掉的下游结果
DOWNSTREAM = {
    "directions": ["gate1", "s3_outline", "s4_detail", "gate2", "s5a_backfill"],
    "detail": ["gate2", "s5a_backfill"],
}


class StageError(Exception):
    pass


class Project:
    lock = threading.Lock()
    jobs = {}  # id -> 当前后台任务的状态，只存在内存里

    def __init__(self, pid):
        if not re.fullmatch(r"[0-9a-z-]+", pid):
            raise StageError("项目编号不合法")
        self.id, self.dir = pid, OUTPUT / f"wb_{pid}"
        if not (self.dir / "workbench.json").exists():
            raise StageError("项目不存在")

    @classmethod
    def create(cls, filename, text, cfg):
        title, chapters = parse(text)
        pid = time.strftime("%m%d-%H%M") + "-" + secrets.token_hex(2)
        d = OUTPUT / f"wb_{pid}"
        d.mkdir(parents=True)
        (d / "source.txt").write_text(text, encoding="utf-8")
        cfg = {**default_config(), **cfg, "id": pid, "filename": filename, "title": title or filename,
               "step": "upload", "created": time.strftime("%Y-%m-%d %H:%M")}
        (d / "workbench.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        return cls(pid)

    # 配置
    @property
    def cfg(self):
        return json.loads((self.dir / "workbench.json").read_text(encoding="utf-8"))

    def update(self, **kw):
        cfg = {**self.cfg, **kw}
        (self.dir / "workbench.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        return cfg

    def pipeline(self, s5b_model=None):
        cfg = self.cfg
        args = types.SimpleNamespace(book=str(self.dir / "source.txt"), out=str(self.dir), target=int(cfg["target"]),
                                     free=int(cfg["free"]), tags=cfg["tags"], note=cfg["note"], direction="A",
                                     start=None, only=None, rewrite=False, max_chapters=0,
                                     auto_revise=bool(cfg.get("auto_revise")),
                                     move_mode=cfg.get("move_mode", "library_first"))
        llm = run.LLM(run.load_env())
        llm.per_stage = {s: m for s, m in cfg["models"].items() if m}
        if s5b_model:
            llm.per_stage["s5b"] = s5b_model
        return run.Pipeline(args, llm)

    def load(self, name):
        f = self.dir / f"{name}.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    def clear(self, step):
        for name in DOWNSTREAM.get(step, []):
            (self.dir / f"{name}.json").unlink(missing_ok=True)
        shutil.rmtree(self.dir / "s5b", ignore_errors=True)
        shutil.rmtree(self.dir / "s5b_compare", ignore_errors=True)
        (self.dir / "manuscript.txt").unlink(missing_ok=True)

    # 后台任务：同一项目同时只跑一个
    def job(self):
        return Project.jobs.get(self.id, {"running": False})

    def start(self, name, fn):
        with Project.lock:
            if self.job().get("running"):
                raise StageError("还有任务在跑，等它结束或先停止")
            Project.jobs[self.id] = {"running": True, "name": name, "message": "开始……", "error": "", "stop": False}

        def work():
            j = Project.jobs[self.id]
            try:
                fn(j)
                j["message"] = "已停止" if j["stop"] else "完成"
            except BaseException as e:  # run.LLM 失败时 sys.exit，这里一并接住
                j["error"] = str(e) or e.__class__.__name__
                traceback.print_exc()
            finally:
                j.pop("chapter", None)
                j["running"] = False
        threading.Thread(target=work, daemon=True).start()

    # ---------- 各步动作 ----------
    def analyze(self, body):
        self.update(**pick(body, "target", "free", "tags", "note", "models"))

        def fn(j):
            p = self.pipeline()
            j["message"] = "正在理解原文……"
            p.s1()
            j["message"] = "正在生成三个方向……"
            p.s2()
            self.update(step="directions")
        self.start("analyze", fn)

    def regen_directions(self, body):
        self.update(**pick(body, "note", "models"))

        def fn(j):
            j["message"] = "正在重新生成三个方向……"
            self.clear("directions")
            self.pipeline().s2()
            self.update(step="directions")
        self.start("directions", fn)

    def choose(self, body):
        mode = body.get("mode")
        if mode not in ("pick", "custom", "auto"):
            raise StageError("选择方式不对")
        if mode == "pick" and not body.get("strategy"):
            raise StageError("没有选方向")
        if mode == "custom" and not body.get("idea", "").strip():
            raise StageError("自定义方向需要写一句想法")
        self.update(**pick(body, "note", "models"))

        def fn(j):
            self.clear("directions")
            p = self.pipeline()
            reason = ""
            if mode == "custom":
                j["message"] = "正在把你的想法补成完整方向……"
                strategy = p.custom_direction(body["idea"].strip())["strategy"]
            elif mode == "auto":
                j["message"] = "正在让模型选方向……"
                strategy, reason, _ = p.auto_select()
            else:
                strategy = body["strategy"]
            p.save("gate1", {"stage": "选方向", "mode": mode, "selected": strategy, "reason": reason,
                             "idea": body.get("idea", ""), "editor_note": p.args.note or "无"})
            self.make_outline(j, p)
            j["message"] = "正在生成细纲……"
            p.s4()
            self.update(step="detail")
        self.start("choose", fn)

    @staticmethod
    def outline_gap(p):
        return [c["name"] for c in p.load("s3_outline")["checks"] if not c["pass"] and "大事件覆盖" in c["name"]]

    def make_outline(self, j, p, rerun=True):
        """大纲不给用户确认，没排满所有章就重跑一次，仍不行就停下，不让问题流到细纲。"""
        for attempt in range(2):
            if rerun or attempt:
                j["message"] = "正在生成大纲……" if not attempt else "大纲没排满，正在重新生成……"
                p.s3()
            gap = self.outline_gap(p)
            if not gap:
                return
        raise StageError(f"大纲两次都没排满（{gap[0]}），请重新确认方向或换模型")

    def regen_detail(self, body):
        self.update(**pick(body, "models"))

        def fn(j):
            self.clear("detail")
            p = self.pipeline()
            self.make_outline(j, p, rerun=bool(self.outline_gap(p)))
            j["message"] = "正在重新生成细纲……"
            p.s4()
            self.update(step="detail")
        self.start("detail", fn)

    def save_detail(self, body):
        chapters = body.get("chapters")
        if not isinstance(chapters, list) or not chapters:
            raise StageError("细纲内容为空")
        data = self.load("s4_detail")
        data["output"]["chapters"] = chapters
        data["checks"] = self.pipeline().detail_checks(chapters)
        data["edited"] = True
        (self.dir / "s4_detail.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return data["checks"]

    def confirm_detail(self, body):
        if body.get("chapters"):
            self.save_detail(body)
        _, _, first, last, _ = self.pipeline().plan()
        idx = [int(c.get("index", 0)) for c in self.load("s4_detail")["output"]["chapters"]]
        if idx != list(range(first, last + 1)):
            raise StageError(f"细纲要覆盖第 {first}～{last} 章，现在是第 {idx[0]}～{idx[-1]} 章，请重新生成细纲")
        self.update(**pick(body, "models"))

        def fn(j):
            self.clear("detail")
            p = self.pipeline()
            p.save("gate2", {"stage": "确认细纲", "confirmed": time.strftime("%Y-%m-%d %H:%M")})
            j["message"] = "正在往原文里补伏笔……"
            p.s5a()
            self.update(step="writing")
            self.write_loop(j, p)
        self.start("write", fn)

    def write(self, body):
        self.update(**pick(body, "models"))
        self.start("write", lambda j: self.write_loop(j, self.pipeline()))

    def write_loop(self, j, p):
        _, _, first, last, _ = p.plan()
        for i in range(first, last + 1):
            if j["stop"]:
                return
            if p.chapter_file(i).exists():
                continue
            j["message"] = f"正在写第 {i} 章……"
            j["chapter"] = i
            p.write_chapter(i, p.args.auto_revise)
        p.write_manuscript()

    def stop(self, body):
        j = self.job()
        if j.get("running"):
            j["stop"] = True
            j["message"] = "写完当前这一章就停"

    def rewrite(self, body):
        i = int(body["chapter"])
        self.update(**pick(body, "models"))

        def fn(j):
            j["message"] = f"正在重写第 {i} 章……"
            j["chapter"] = i
            p = self.pipeline()
            p.write_chapter(i, p.args.auto_revise)
        self.start("rewrite", fn)

    def revise(self, body):
        i, instruction = int(body["chapter"]), body.get("instruction", "").strip()
        if not instruction:
            raise StageError("先写修改意见")
        self.update(**pick(body, "models"))

        def fn(j):
            j["message"] = f"正在按意见修改第 {i} 章……"
            j["chapter"] = i
            self.pipeline().revise_chapter(i, instruction)
        self.start("revise", fn)

    def restore(self, body):
        self.pipeline().restore_chapter(int(body["chapter"]))

    # 多模型对比：同一章、同样的前文和细纲，几个模型同时写，候选稿放在 s5b_compare/chNN/
    def compare_dir(self, i):
        return self.dir / "s5b_compare" / f"ch{i:02d}"

    def compare(self, body):
        i = int(body["chapter"])
        models = [m.strip() for m in body.get("models", []) if m.strip()]
        if not 2 <= len(models) <= 4:
            raise StageError("选 2～4 个模型来对比")
        self.update(compare_models=models)

        def fn(j):
            d = self.compare_dir(i)
            shutil.rmtree(d, ignore_errors=True)
            done, failed = [], []
            j["chapter"] = i
            j["message"] = f"{len(models)} 个模型正在同时写第 {i} 章……"

            def one(m):
                try:
                    p = self.pipeline(s5b_model=m)
                    p.write_chapter(i, False, target=d / f"{m.replace('/', '__')}.json")
                    done.append(m)
                except BaseException as e:  # 单个模型失败不影响其他模型
                    failed.append(f"{m}：{e}")
                j["message"] = f"第 {i} 章：{len(done)}/{len(models)} 个模型写完" + (f"，{len(failed)} 个失败" if failed else "")
            with ThreadPoolExecutor(max_workers=len(models)) as ex:
                list(ex.map(one, models))
            if failed and not done:
                raise StageError("全部失败：" + "；".join(failed))
            if failed:
                j["error"] = "部分模型失败：" + "；".join(failed)
        self.start("compare", fn)

    def candidates(self, i):
        d = self.compare_dir(i)
        out = []
        for f in sorted(d.glob("*.json")) if d.exists() else []:
            c = json.loads(f.read_text(encoding="utf-8"))
            out.append({"model": f.stem.replace("__", "/"), "returned_model": c.get("model"), "text": c["text"],
                        "stats": c["stats"], "checks": c["checks"], "seconds": c.get("seconds"),
                        "cost": c.get("usage", {}).get("cost")})
        order = self.cfg.get("compare_models") or COMPARE_MODELS
        out.sort(key=lambda x: order.index(x["model"]) if x["model"] in order else 99)
        return {"chapter": i, "candidates": out}

    def adopt(self, body):
        i, model = int(body["chapter"]), body["model"]
        src = self.compare_dir(i) / f"{model.replace('/', '__')}.json"
        if not src.exists():
            raise StageError("没有这个模型的候选稿")
        p = self.pipeline()
        data = json.loads(src.read_text(encoding="utf-8"))
        data["stats"], data["checks"] = p.chapter_checks(data["text"], i)  # 前文可能变过，按现在的前文重算
        data["adopted_from"] = model
        f = p.chapter_file(i)
        if f.exists():
            old = json.loads(f.read_text(encoding="utf-8"))
            data["previous"] = {"text": old["text"], "stats": old["stats"], "checks": old["checks"]}
        f.parent.mkdir(exist_ok=True)
        f.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def save_chapter(self, i, body):
        p = self.pipeline()
        if not p.chapter_file(i).exists():
            raise StageError("这一章还没写")
        p.save_chapter_edit(i, body.get("text", "").strip())
        return json.loads(p.chapter_file(i).read_text(encoding="utf-8"))

    def finish(self, body):
        p = self.pipeline()
        _, _, first, last, _ = p.plan()
        missing = [i for i in range(first, last + 1) if not p.chapter_file(i).exists()]
        if missing:
            raise StageError(f"还有第 {missing[0]} 章等 {len(missing)} 章没写")
        p.write_manuscript()
        self.update(step="done")

    # ---------- 给前端的状态 ----------
    def state(self):
        cfg = self.cfg
        p = self.pipeline()
        s2, gate1, s4 = self.load("s2_directions"), self.load("gate1"), self.load("s4_detail")
        plan = None
        if gate1 and (self.dir / "s3_outline.json").exists():
            _, cut, first, last, n = p.plan()
            plan = {"cut": cut, "first": first, "last": last, "n": n}
        written = []
        for f in sorted((self.dir / "s5b").glob("ch*.json")) if (self.dir / "s5b").exists() else []:
            c = json.loads(f.read_text(encoding="utf-8"))
            written.append({"index": int(f.stem[2:]), "words": c["stats"]["words"], "edited": c.get("edited", False),
                            "bad": sum(not x["pass"] for x in c["checks"])})
        return {
            "config": cfg, "job": {k: v for k, v in self.job().items() if k != "stop"},
            "stages": MODEL_STAGES, "default_model": p.llm.default,
            "chapters": [{"index": c["index"], "words": run.count_words(c["text"]),
                          "head": run.paragraphs(c["text"])[0][:40] if c["text"] else ""} for c in p.chapters],
            "baseline": {k: p.baseline[k] for k in ("total_words", "median_words", "dialogue_ratio", "para_avg", "pov")},
            "directions": s2 and {"list": s2["output"].get("directions", []), "notes": s2["output"].get("notes", ""),
                                  "checks": s2["checks"], "custom_idea": s2.get("custom", {}).get("idea", "")},
            "gate1": gate1, "plan": plan,
            "detail": s4 and {"chapters": s4["output"]["chapters"], "checks": s4["checks"],
                              "edited": s4.get("edited", False)},
            "written": written,
            "compare_models": cfg.get("compare_models") or COMPARE_MODELS,
            "compared": sorted(int(d.name[2:]) for d in (self.dir / "s5b_compare").glob("ch*") if any(d.glob("*.json")))
            if (self.dir / "s5b_compare").exists() else [],
            "ai_tics": [w for w in run.TICS if w not in "".join(c["text"] for c in p.chapters)],
        }

    def chapter(self, i):
        f = self.pipeline().chapter_file(i)
        if not f.exists():
            raise StageError("这一章还没写")
        c = json.loads(f.read_text(encoding="utf-8"))
        return {**{k: c.get(k) for k in ("text", "stats", "checks", "outline", "model", "seconds", "edited")},
                "suggestion": run.style_instruction(c["stats"].get("style", {"repeats": [], "tics": {}})),
                "revision": c.get("revision"), "has_previous": "previous" in c, "auto_revised": "draft" in c,
                "adopted_from": c.get("adopted_from")}


def default_config():
    return {"target": 20000, "free": 4, "tags": "", "note": "", "auto_revise": False, "move_mode": "library_first",
            "models": {s: "" for s in MODEL_STAGES}}


def pick(body, *keys):
    return {k: body[k] for k in keys if k in body}


def parse(text):
    try:
        return run.split_chapters(text)
    except SystemExit as e:  # split_chapters 识别失败时 sys.exit
        raise StageError(str(e))


def projects():
    out = []
    for d in sorted(OUTPUT.glob("wb_*/workbench.json"), reverse=True):
        c = json.loads(d.read_text(encoding="utf-8"))
        out.append({k: c.get(k) for k in ("id", "title", "step", "created")})
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        if not self.path.startswith("/api/p/") or self.command != "GET":
            super().log_message(fmt, *a)

    def send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20 * 1024 * 1024:
            raise StageError("文件太大")
        return json.loads(self.rfile.read(n) or b"{}")

    def handle_any(self, method):
        path = self.path.split("?")[0]
        try:
            if method == "GET" and path == "/":
                return self.send(200, (ROOT / "workbench.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/api/projects":
                if method == "GET":
                    return self.send(200, {"projects": projects(), "default": default_config(),
                                           "stages": MODEL_STAGES, "default_model": run.load_env().get("MODEL", "")})
                b = self.body()
                return self.send(200, {"id": Project.create(b.get("filename", "未命名"), b.get("text", ""),
                                                            pick(b, "target", "free", "tags", "note", "models", "move_mode")).id})
            m = re.fullmatch(r"/api/p/([^/]+)(?:/(\w+))?(?:/(\d+))?", path)
            if not m:
                return self.send(404, {"error": "没有这个地址"})
            p, action, num = Project(m.group(1)), m.group(2), m.group(3)
            if method == "GET":
                if action is None:
                    return self.send(200, p.state())
                if action == "chapter":
                    return self.send(200, p.chapter(int(num)))
                if action == "compare":
                    return self.send(200, p.candidates(int(num)))
                if action == "manuscript":
                    f = p.dir / "manuscript.txt"
                    name = quote(f"{p.cfg['title']}_续写.txt")
                    return self.send(200, f.read_bytes(), "text/plain; charset=utf-8",
                                     {"Content-Disposition": f"attachment; filename*=UTF-8''{name}"})
            if method == "PUT":
                if action == "config":
                    return self.send(200, p.update(**pick(self.body(), "target", "free", "tags", "note", "models", "auto_revise", "move_mode")))
                if action == "detail":
                    return self.send(200, {"checks": p.save_detail(self.body())})
                if action == "chapter":
                    return self.send(200, p.save_chapter(int(num), self.body()))
            if method == "POST":
                acts = {"analyze": p.analyze, "directions": p.regen_directions, "choose": p.choose,
                        "detail": p.regen_detail, "confirm": p.confirm_detail, "write": p.write, "stop": p.stop,
                        "rewrite": p.rewrite, "revise": p.revise, "restore": p.restore, "finish": p.finish,
                        "compare": p.compare, "adopt": p.adopt}
                if action in acts:
                    acts[action](self.body())
                    return self.send(200, {"ok": True})
            self.send(404, {"error": "没有这个操作"})
        except (StageError, SystemExit) as e:  # run.py 的配置错误走 sys.exit
            self.send(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            self.send(500, {"error": f"{e.__class__.__name__}: {e}"})

    def do_GET(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")

    def do_PUT(self):
        self.handle_any("PUT")


if __name__ == "__main__":
    OUTPUT.mkdir(exist_ok=True)
    print(f"工作台已启动：http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
