"""Isolated real-model baseline capture/replay; manuscripts and outputs stay local."""
import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def backup(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True) as src, sqlite3.connect(destination) as target:
        src.backup(target)


def capture(args):
    root, output = args.code.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    backup(root / "data/novel.db", output / "before.db")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    with (output / "source.tar").open("wb") as stream:
        subprocess.run(["git", "archive", commit], cwd=root, stdout=stream, check=True)
    code = output / "source"
    code.mkdir()
    with tarfile.open(output / "source.tar") as archive:
        archive.extractall(code, filter="data")
    write_json(output / "manifest.json", {"captured_at": datetime.now(timezone.utc).isoformat(), "commit": commit, "database_sha256": hashlib.sha256((output / "before.db").read_bytes()).hexdigest()})
    print(output)


async def run(args):
    from dotenv import dotenv_values
    output, code = args.output.resolve(), args.code.resolve()
    output.mkdir(parents=True, exist_ok=True)
    database = output / "run.db"
    if database.exists():
        raise SystemExit("输出目录已有运行数据库；请使用新的目录，避免污染实验。")
    env = dotenv_values(args.env_file)
    os.environ.update({key: value for key, value in env.items() if value is not None})
    parent = json.loads((args.reuse_from / "results.json").read_text()) if args.reuse_from else None
    frozen = json.loads(args.model_settings_from.read_text()) if args.model_settings_from else parent.get("identity") if parent else None
    if frozen and frozen.get("connections") and frozen.get("models"):
        os.environ["NOVEL_CONNECTIONS"] = json.dumps(frozen["connections"])
        os.environ["NOVEL_MODELS"] = json.dumps(frozen["models"])
    if args.reuse_from:
        backup(args.reuse_from.resolve() / "run.db", database)
    os.environ.update({"NOVEL_DATABASE_URL": f"sqlite:///{database}", "NOVEL_DATA_DIR": str(output / "artifacts"), "NOVEL_MODE": args.mode})
    sys.path.insert(0, str(code))
    from alembic import command
    from alembic.config import Config
    from sqlmodel import Session
    from app.config import ROOT, settings
    if ROOT.resolve() != code:
        raise RuntimeError("实验导入了错误的代码目录，停止运行")
    from app.db import engine
    from app.models import Project, Version, SourceChapter, OutlineRevision, ChapterPlanRow, StoryBibleSnapshot, LLMCall
    from app.schemas import CreateProject, CreateVersion, ActionInput, Direction
    from app.services import one, rows, save, latest_outline, latest_plans, version_bible
    from app.api.projects import upload_text, create_version
    from app.api.versions import confirm_outline
    from app.pipeline.runner import runner
    from eval.metrics import report
    command.upgrade(Config(str(code / "alembic.ini")), "head")
    samples = json.loads(args.samples.read_text())
    baseline_call_id = max((call.id for call in rows(LLMCall)), default=0)
    identity = {"code": str(code), "mode": settings.mode, "stage": args.from_stage, "reuse_from": str(args.reuse_from) if args.reuse_from else None, "models": settings.models, "connections": {name: connection.model_dump(exclude={"api_key"}) for name, connection in settings.connections.items()}, "started_at": datetime.now(timezone.utc).isoformat(), "starting_call_id": baseline_call_id}
    identity["source_sha256"] = hashlib.sha256(b"".join(str(path.relative_to(code)).encode() + path.read_bytes() for path in sorted((code / "app").rglob("*")) if path.suffix in {".py", ".md", ".txt"})).hexdigest()
    write_json(output / "identity.json", identity)
    results = {}

    async def wait(project_id, version_id, wanted):
        deadline = time.monotonic() + args.timeout
        model, ident = (Version, version_id) if version_id else (Project, project_id)
        while time.monotonic() < deadline:
            item = one(model, ident)
            if item.status in {wanted, "failed", "abandoned"} and not runner.busy(project_id, version_id):
                return item
            await asyncio.sleep(1)
        raise TimeoutError(f"{model.__name__} {ident} timed out")

    async def sample_run(sample):
        project_id, version_id = None, None
        name = sample["id"]
        try:
            if args.from_stage == "understand":
                from app.checks import count_words, split_chapters, source_index
                from app.pipeline.context import NodeContext
                from app.pipeline.nodes.n1_understand import run as understand
                text = Path(sample["text_path"]).read_text()
                project = Project(title=sample["title"], genre_tags=sample.get("genre_tags", []), source_word_count=count_words(text), created_by="baseline-eval")
                save(project)
                project_id = project.id
                previous = 0
                for title, content in split_chapters(text):
                    index = max(previous + 1, source_index(title, previous + 1))
                    save(SourceChapter(project_id=project_id, index=index, title=title, content=content))
                    previous = index
                await understand(NodeContext(project_id))
                project.status, project.current_node = "understood", "N1"
                save(project)
                snapshots = rows(StoryBibleSnapshot, StoryBibleSnapshot.project_id == project_id)
                result = {"status": "understood", "error": None, "metrics": {"source_words": count_words(text), "source_chapters": len(rows(SourceChapter, SourceChapter.project_id == project_id)), "bible_warnings": len(snapshots[-1].warnings)}}
            elif parent:
                old_id = parent["samples"][name].get("version_id")
                if old_id is None:
                    raise ValueError("父实验没有方向/大纲产物，不能从后续阶段重放")
                old = one(Version, old_id)
                project_id = old.project_id
                if args.from_stage == "directions":
                    project = one(Project, project_id)
                    project.status, project.current_node, project.error = "queued", "N2", None
                    save(project)
                    runner.enqueue(project_id)
                    ready = await wait(project_id, None, "awaiting_direction")
                    if ready.status == "failed":
                        raise RuntimeError(ready.error)
                    with Session(engine) as session:
                        version = await create_version(project_id, CreateVersion(source="auto", target_words=args.target_words, editor="baseline-eval"), session)
                    version_id = version.id
                elif args.from_stage == "outline":
                    with Session(engine) as session:
                        version = await create_version(project_id, CreateVersion(source="edited", candidate_id=old.direction_candidate_id, direction=Direction.model_validate(old.direction), target_words=args.target_words, editor="baseline-eval"), session)
                    version_id = version.id
                else:
                    version = Version(project_id=project_id, direction_source="edited", direction_candidate_id=old.direction_candidate_id, direction=old.direction, target_words=old.target_words, total_chapters=old.total_chapters, status="awaiting_outline" if args.from_stage == "plans" else "writing", current_node="N5" if args.from_stage == "plans" else "N6")
                    save(version)
                    version_id = version.id
                    outline = latest_outline(old_id)
                    if not outline:
                        raise ValueError("父实验没有大纲，不能重放细纲或正文")
                    save(OutlineRevision(version_id=version_id, rev=1, data=outline.data, confirmed=args.from_stage == "write", warnings=outline.warnings))
                    if args.from_stage == "write":
                        plans = latest_plans(old_id)
                        if not plans:
                            raise ValueError("父实验没有细纲，不能重放正文")
                        save(*(ChapterPlanRow(version_id=version_id, index=p.index, data=p.data) for p in plans))
                        end = max(c.index for c in rows(SourceChapter, SourceChapter.project_id == project_id))
                        seed = version_bible(old_id, before=end + 1)
                        save(StoryBibleSnapshot(project_id=project_id, version_id=version_id, after_chapter=end, data=seed.model_dump()))
                        runner.enqueue(project_id, version_id)
            else:
                text = Path(sample["text_path"]).read_text()
                with Session(engine) as session:
                    project = await upload_text(CreateProject(title=sample["title"], text=text, genre_tags=sample.get("genre_tags", []), editor="baseline-eval"), session)
                project_id = project.id
                ready = await wait(project_id, None, "awaiting_direction")
                if ready.status == "failed":
                    raise RuntimeError(ready.error)
                with Session(engine) as session:
                    version = await create_version(project_id, CreateVersion(source="auto", target_words=args.target_words, editor="baseline-eval"), session)
                version_id = version.id
            if args.from_stage != "understand":
                if not parent or args.from_stage in {"directions", "outline"}:
                    ready = await wait(project_id, version_id, "awaiting_outline")
                    if ready.status == "failed":
                        raise RuntimeError(ready.error)
                if not parent or args.from_stage != "write":
                    with Session(engine) as session:
                        await confirm_outline(version_id, ActionInput(editor="baseline-eval", reason="隔离离线评测自动推进，不表示编辑验收"), session)
                final = await wait(project_id, version_id, "awaiting_review")
                result = {"status": final.status, "error": final.error, "metrics": report(version_id)}
        except Exception as error:
            result = {"status": "failed", "error": str(error)}
            if version_id:
                result["metrics"] = report(version_id)
        calls = [call for call in rows(LLMCall, LLMCall.project_id == project_id) if call.id > baseline_call_id] if project_id else []
        node_metrics = {}
        for call in calls:
            node = node_metrics.setdefault(call.node, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0})
            node["calls"] += 1
            node["input_tokens"] += call.input_tokens
            node["output_tokens"] += call.output_tokens
            node["latency_ms"] += call.latency_ms
        result.update({"project_id": project_id, "version_id": version_id, "sample": sample, "input_sha256": hashlib.sha256(Path(sample["text_path"]).read_bytes()).hexdigest(), "node_metrics": node_metrics, "segment_calls": len(calls), "segment_input_tokens": sum(c.input_tokens for c in calls), "segment_output_tokens": sum(c.output_tokens for c in calls), "segment_latency_ms": sum(c.latency_ms for c in calls)})
        results[name] = result
        write_json(output / f"{name}.json", result)
        write_json(output / "results.json", {"identity": identity, "samples": results})
        print(name, result["status"], "version", version_id, flush=True)

    try:
        await asyncio.gather(*(sample_run(sample) for sample in samples))
    finally:
        await runner.close()
        write_json(output / "results.json", {"identity": identity, "samples": results})


def compare(args):
    before, after = [json.loads(path.read_text()) for path in args.reports]
    comparison = {}
    for name in before["samples"].keys() & after["samples"].keys():
        old, new = before["samples"][name], after["samples"][name]
        old_metrics, new_metrics = old.get("normalized_metrics", old.get("metrics", {})), new.get("normalized_metrics", new.get("metrics", {}))
        delta = {key: new_metrics[key] - value for key, value in old_metrics.items() if key != "version_id" and isinstance(value, (int, float)) and isinstance(new_metrics.get(key), (int, float))}
        partial = old.get("status") == "partial" or new.get("status") == "partial"
        if partial:
            delta.pop("completion_rate", None)
        same_stage = before["identity"]["stage"] == after["identity"]["stage"]
        nodes = old.get("node_metrics", {}).keys() & new.get("node_metrics", {}).keys()
        node_delta = {node: {key: new["node_metrics"][node][key] - value for key, value in old["node_metrics"][node].items()} for node in nodes}
        comparison[name] = {"before_status": old["status"], "after_status": new["status"], "partial": partial, "completion_comparable": not partial, "same_input": old["input_sha256"] == new["input_sha256"] if old.get("input_sha256") and new.get("input_sha256") else None, "metric_delta": delta, "same_stage": same_stage, "stage_call_delta": new["segment_calls"] - old["segment_calls"] if same_stage else None, "stage_input_token_delta": new["segment_input_tokens"] - old["segment_input_tokens"] if same_stage else None, "per_node_delta": node_delta, "notes": "合并改动比较不能归因到某一个改动；局部重放须使用相同原文、方向、大纲和模型参数。full与局部重放的总成本不直接比较，只按节点对齐。"}
    same_models = all(before["identity"].get(key) == after["identity"].get(key) for key in ("models", "connections"))
    write_json(args.output, {"before": before["identity"], "after": after["identity"], "same_model_settings": same_models, "missing_before": sorted(after["samples"].keys() - before["samples"].keys()), "missing_after": sorted(before["samples"].keys() - after["samples"].keys()), "samples": comparison})
    print(args.output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture_parser = sub.add_parser("capture")
    capture_parser.add_argument("--code", type=Path, default=Path.cwd())
    capture_parser.add_argument("--output", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--code", type=Path, required=True)
    run_parser.add_argument("--samples", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--env-file", type=Path, required=True)
    run_parser.add_argument("--target-words", type=int, default=20000)
    run_parser.add_argument("--mode", choices=["live", "demo"], default="live")
    run_parser.add_argument("--timeout", type=int, default=3600)
    run_parser.add_argument("--reuse-from", type=Path)
    run_parser.add_argument("--from-stage", "--stage", dest="from_stage", choices=["full", "understand", "directions", "outline", "plans", "write"], default="full")
    run_parser.add_argument("--model-settings-from", type=Path)
    compare_parser = sub.add_parser("compare")
    compare_parser.add_argument("reports", nargs=2, type=Path)
    compare_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "capture":
        capture(args)
    elif args.command == "run":
        if bool(args.reuse_from) != (args.from_stage in {"directions", "outline", "plans", "write"}):
            parser.error("局部阶段重放必须同时指定 --reuse-from 和非full的 --from-stage")
        asyncio.run(run(args))
    else:
        compare(args)
