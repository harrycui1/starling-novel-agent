"""Run the full-text workflow in an isolated local database for editorial comparison."""
import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def safe_parameters(value):
    if isinstance(value, dict):
        return {key: safe_parameters(item) for key, item in value.items()
                if not re.search(r"key|secret|token(?!s)|authorization|password|credential", key, re.I)}
    if isinstance(value, list):
        return [safe_parameters(item) for item in value]
    return value


async def run(args):
    from dotenv import dotenv_values
    output = args.output.resolve()
    database = output / "run.db"
    if database.exists():
        raise ValueError("输出目录已有 run.db，请使用新目录，避免覆盖实验。")
    samples = json.loads(args.samples.read_text())
    if not samples or len({s["id"] for s in samples}) != len(samples):
        raise ValueError("样本须为非空列表，且 id 不能重复")
    for sample in samples:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", sample["id"]):
            raise ValueError("样本 id 只允许英文字母、数字、下划线和短横线")
        path = Path(sample["text_path"])
        sample["text_path"] = str((args.samples.resolve().parent / path).resolve())
    output.mkdir(parents=True, exist_ok=True)
    if args.env_file:
        os.environ.update({k: v for k, v in dotenv_values(args.env_file).items() if v is not None})
    os.environ.update({"NOVEL_DATABASE_URL": f"sqlite:///{database}", "NOVEL_DATA_DIR": str(output / "artifacts"), "NOVEL_MODE": args.mode})
    sys.path.insert(0, str(ROOT))
    from alembic import command
    from alembic.config import Config
    from sqlmodel import Session
    from app.config import settings
    from app.db import engine
    from app.models import Project, Version, DirectionCandidate, ChapterReview, LLMCall
    from app.schemas import CreateProject, CreateVersion, ActionInput
    from app.services import one, rows, current_drafts, latest_outline, source_understanding
    from app.api.projects import upload_text, create_version
    from app.api.versions import confirm_outline, export
    from app.pipeline.runner import runner
    from eval.metrics import report

    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    identity = {"code": str(ROOT), "mode": settings.mode, "target_words": args.target_words,
                "models": settings.models,
                "connections": {name: {"protocol": c.protocol, "model": c.model, "parameters": safe_parameters(c.parameters)} for name, c in settings.connections.items()},
                "started_at": datetime.now(timezone.utc).isoformat(),
                "selection": "评测驱动选择首个方向并确认大纲，不代表编辑验收；未提交版本。",
                "source_sha256": hashlib.sha256(b"".join(str(p.relative_to(ROOT)).encode() + p.read_bytes() for p in sorted((ROOT / "app").rglob("*")) if p.suffix in {".py", ".md", ".txt"})).hexdigest()}
    write_json(output / "identity.json", identity)
    results = {}
    limit = asyncio.Semaphore(3)

    async def sample_run(sample):
        async with limit:
            pid, vid = None, None
            started = time.monotonic()
            deadline = started + args.timeout
            folder = output / sample["id"]
            folder.mkdir(exist_ok=True)
            result = {"sample": sample, "status": "interrupted"}
            async def wait(ident, version, status):
                while time.monotonic() < deadline:
                    item = one(Version if version else Project, ident)
                    if item.status in {status, "failed", "abandoned"} and not runner.busy(pid, ident if version else None):
                        if item.status != status:
                            raise RuntimeError(item.error or item.status)
                        return item
                    await asyncio.sleep(.1 if args.mode == "demo" else 1)
                raise TimeoutError(f"样本 {sample['id']} 超过 {args.timeout} 秒")
            try:
                raw = Path(sample["text_path"]).read_bytes()
                result["input_sha256"] = hashlib.sha256(raw).hexdigest()
                with Session(engine) as session:
                    project = await upload_text(CreateProject(title=sample["title"], text=raw.decode("utf-8-sig"), genre_tags=sample.get("genre_tags", []), editor="eval-driver"), session)
                pid = project.id
                await wait(pid, False, "awaiting_direction")
                candidates = rows(DirectionCandidate, DirectionCandidate.project_id == pid, DirectionCandidate.batch_id == one(Project, pid).active_batch, order=DirectionCandidate.id)
                write_json(folder / "directions.json", [c.model_dump() for c in candidates])
                write_json(folder / "understanding.json", source_understanding(pid).data)
                with Session(engine) as session:
                    version = await create_version(pid, CreateVersion(source="candidate", candidate_id=candidates[0].id, target_words=args.target_words, editor="eval-driver", reason="评测驱动选择首个方向，不代表编辑验收"), session)
                vid = version.id
                await wait(vid, True, "awaiting_outline")
                write_json(folder / "outline.json", latest_outline(vid).data)
                with Session(engine) as session:
                    await confirm_outline(vid, ActionInput(editor="eval-driver", reason="评测驱动推进，不代表编辑验收"), session)
                final = await wait(vid, True, "awaiting_review")
                result["status"] = final.status
            except Exception as error:
                result.update(status="failed", error=str(error))
                tasks = [task for (project_id, _), task in list(runner.tasks.items()) if project_id == pid]
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                result.update(project_id=pid, version_id=vid, elapsed_seconds=round(time.monotonic() - started, 3))
                calls = rows(LLMCall, LLMCall.project_id == pid, order=LLMCall.id) if pid else []
                result.update(calls=len(calls), input_tokens=sum(c.input_tokens for c in calls), output_tokens=sum(c.output_tokens for c in calls), model_latency_ms=sum(c.latency_ms for c in calls))
                write_json(folder / "calls.json", [c.model_dump() for c in calls])
                if vid:
                    result["metrics"] = report(vid)
                    drafts = current_drafts(vid)
                    label = "【演示数据，仅用于验证操作流程】\n\n" if settings.mode == "demo" else ""
                    (folder / "continuation.txt").write_text(label + "\n\n".join(d.content for d in drafts))
                    write_json(folder / "reviews.json", [r.model_dump() for r in rows(ChapterReview, ChapterReview.draft_id.in_([d.id for d in drafts]), order=ChapterReview.id)])
                    with Session(engine) as session:
                        (folder / "manuscript.txt").write_bytes(export(vid, "txt", session).body)
                        (folder / "manuscript.docx").write_bytes(export(vid, "docx", session).body)
                results[sample["id"]] = result
                write_json(folder / "result.json", result)
                write_json(output / "results.json", {"identity": identity, "samples": results})
                print(sample["id"], result["status"], "version", vid, "calls", len(calls), flush=True)

    try:
        await asyncio.gather(*(sample_run(s) for s in samples))
    finally:
        await runner.close()
        write_json(output / "results.json", {"identity": identity, "samples": results})
    return all(r["status"] == "awaiting_review" for r in results.values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--mode", choices=["live", "demo"], default="live")
    parser.add_argument("--target-words", type=int, default=20000)
    parser.add_argument("--timeout", type=float, default=3600)
    args = parser.parse_args()
    if (args.output / "run.db").exists():
        parser.error("输出目录已有 run.db，请使用新目录，避免覆盖实验。")
    try:
        sys.exit(0 if asyncio.run(run(args)) else 1)
    except Exception as error:
        args.output.mkdir(parents=True, exist_ok=True)
        write_json(args.output / "error.json", {"status": "failed", "error": str(error)})
        raise SystemExit(str(error)) from None
