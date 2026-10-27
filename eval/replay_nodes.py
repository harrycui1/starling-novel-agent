"""Replay only N2/N3 or N5 against frozen parent artifacts, without writing prose."""
import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path


async def main(args):
    from dotenv import dotenv_values
    args.output.mkdir(parents=True, exist_ok=False)
    database = args.output.resolve() / "run.db"
    with sqlite3.connect(f"file:{args.parent_db.resolve()}?mode=ro", uri=True) as old, sqlite3.connect(database) as new:
        old.backup(new)
    os.environ.update({key: value for key, value in dotenv_values(args.env_file).items() if value is not None})
    identity = json.loads(args.model_settings_from.read_text())
    os.environ.update({"NOVEL_CONNECTIONS": json.dumps(identity["connections"]), "NOVEL_MODELS": json.dumps(identity["models"]), "NOVEL_DATABASE_URL": f"sqlite:///{database}", "NOVEL_DATA_DIR": str(args.output.resolve() / "artifacts"), "NOVEL_MODE": args.mode})
    sys.path.insert(0, str(args.code.resolve()))
    from sqlalchemy import delete, update
    from sqlmodel import Session
    from app.config import ROOT
    from app.db import engine
    from app.models import LLMCall, SourceChapter, StoryBibleSnapshot, ChapterReview, ChapterDraft, ChapterPlanRow, OutlineRevision, EditorAction, PipelineEvent, Version, DirectionCandidate
    from app.services import rows, initial_bible, latest_outline, version_bible
    from app.pipeline.context import NodeContext
    from app.pipeline.nodes import n2_directions, n5_chapter_plan
    assert ROOT.resolve() == args.code.resolve(), "wrong code imported"
    last = max((call.id for call in rows(LLMCall)), default=0)
    ctx = NodeContext(args.project_id, args.version_id if args.stage == "plans" else None)
    if args.stage == "directions":
        # These experiments replay the first N2 invocation from an empty-history
        # baseline. Generated parent choices must not become new avoid/history inputs.
        with Session(engine) as session:
            for model in (ChapterReview, ChapterDraft, ChapterPlanRow, OutlineRevision):
                session.exec(delete(model))
            session.exec(delete(StoryBibleSnapshot).where(StoryBibleSnapshot.version_id != None))
            for model in (LLMCall, EditorAction, PipelineEvent):
                session.exec(update(model).values(version_id=None))
            session.exec(delete(Version))
            session.exec(delete(DirectionCandidate))
            session.commit()
    inputs = {"bible": initial_bible(args.project_id).model_dump()}
    if args.stage == "plans":
        if args.version_id is None:
            raise ValueError("plans stage needs --version-id")
        source_end = max(c.index for c in rows(SourceChapter, SourceChapter.project_id == args.project_id))
        with Session(engine) as session:
            session.exec(delete(StoryBibleSnapshot).where(StoryBibleSnapshot.version_id == args.version_id, StoryBibleSnapshot.after_chapter > source_end))
            session.commit()
        inputs["bible"] = version_bible(args.version_id, before=source_end + 1).model_dump()
        inputs["outline"] = latest_outline(args.version_id).data
    before = [call for call in rows(LLMCall, LLMCall.project_id == args.project_id) if call.node in ({"N2", "N3"} if args.stage == "directions" else {"N5"})]
    result = {"stage": args.stage, "project_id": args.project_id, "version_id": args.version_id, "input_sha256": hashlib.sha256(json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode()).hexdigest(), "parent_database": str(args.parent_db.resolve()), "code": str(args.code.resolve())}
    try:
        outcome = await (n2_directions.run(ctx) if args.stage == "directions" else n5_chapter_plan.run(ctx))
        result.update({"status": outcome.status, "error": None})
    except Exception as error:
        result.update({"status": "failed", "error": str(error)})
    after = [call for call in rows(LLMCall) if call.id > last]
    def metrics(calls):
        return {"calls": len(calls), "input_tokens": sum(c.input_tokens for c in calls), "output_tokens": sum(c.output_tokens for c in calls), "latency_ms": sum(c.latency_ms for c in calls)}
    result.update({"before": metrics(before), "after": metrics(after), "delta": {key: value - metrics(before)[key] for key, value in metrics(after).items()}, "notes": "只重放该节点组；原文、父bible/outline和模型参数固定。directions用于首次N2基线：清空生成的候选与选择历史，避免把父实验输出当成新输入。结果不代表正文质量因果。"})
    (args.output / "node-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["directions", "plans"], required=True)
    parser.add_argument("--code", type=Path, required=True)
    parser.add_argument("--parent-db", type=Path, required=True)
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--version-id", type=int)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--model-settings-from", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["live", "demo"], default="live")
    asyncio.run(main(parser.parse_args()))
