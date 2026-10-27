import asyncio
from app.config import settings
from app.models import Project, Version
from app.services import one, rows, save, emit
from app.pipeline.context import NodeContext
from app.pipeline.nodes import n1_understand, n2_directions, n3_select, n4_outline, n6_write, n7_review

NODES = {"N1": n1_understand.run, "N2": n2_directions.run, "N3": n3_select.run, "N4": n4_outline.run, "N5": n6_write.run, "N6": n6_write.run, "N7": n7_review.run, "N6_EDIT": n6_write.edit}
RUNNING_STATUS = {"N1": "understanding", "N2": "generating_directions", "N3": "judging", "N4": "generating_outline", "N5": "planning_chapters", "N6": "writing", "N7": "reviewing", "N6_EDIT": "writing"}
STOPS = {"awaiting_direction", "awaiting_direction_confirmation", "awaiting_outline", "awaiting_review"}


class Runner:
    def __init__(self):
        self.tasks = {}
        self.limit = asyncio.Semaphore(settings.max_parallel_versions)

    def busy(self, project_id, version_id=None):
        return (project_id, version_id) in self.tasks

    def enqueue(self, project_id, version_id=None):
        key = (project_id, version_id)
        if key in self.tasks:
            return
        task = asyncio.create_task(self.run(project_id, version_id))
        self.tasks[key] = task
        task.add_done_callback(lambda _: self.tasks.pop(key, None))

    async def run(self, project_id, version_id):
        async with self.limit:
            ctx = NodeContext(project_id, version_id)
            model, ident = (Version, version_id) if version_id else (Project, project_id)
            try:
                while True:
                    item = one(model, ident)
                    if item.status == "abandoned":
                        return
                    item.status, item.error = RUNNING_STATUS[item.current_node], None
                    save(item)
                    emit(project_id, version_id, "status", status=item.status, node=item.current_node)
                    result = await NODES[item.current_node](ctx)
                    item = one(model, ident)
                    item.status, item.current_node = result.status, result.next_node
                    save(item)
                    emit(project_id, version_id, "status", status=item.status, node=item.current_node)
                    if result.status in STOPS:
                        return
            except asyncio.CancelledError:
                raise
            except Exception as error:
                item = one(model, ident)
                item.status, item.error = "failed", str(error)[:4000]
                save(item)
                emit(project_id, version_id, "error", message=item.error, node=item.current_node)

    def recover(self):
        for model in (Project, Version):
            for item in rows(model):
                if item.status in set(RUNNING_STATUS.values()) | {"created", "queued"}:
                    item.status, item.error = "failed", "上次运行中断，点击继续将从保存的节点恢复。"
                    save(item)

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


runner = Runner()
