"""Exercise the real DB, API and runner; deterministic models make no network calls."""
from collections import Counter
from copy import deepcopy
import io
import json
import time

from docx import Document


class Workflow:
    def __init__(self, client):
        self.client = client

    def send(self, path, data=None, method="POST", code=200):
        response = self.client.request(method, "/api" + path, json=data or {})
        assert response.status_code == code, response.text
        return response.json()

    def wait(self, path, kind, wanted):
        from app.pipeline.runner import runner
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            response = self.client.get("/api" + path)
            assert response.status_code == 200, response.text
            result = response.json()
            item = result[kind]
            # The status transaction precedes removal of the runner's active task.
            key = (item["project_id"], item["id"]) if kind == "version" else (item["id"], None)
            if item["status"] == wanted and not runner.busy(*key):
                return result
            if item["status"] == "failed" and wanted != "failed":
                raise AssertionError(item["error"])
            time.sleep(.01)
        raise AssertionError(f"timed out: {result}")

    def project(self, text="第1章 雨夜\n林舟将铜钥匙放进左袋，沈砚在门外等他。"):
        project = self.send("/projects", {"title": "流程验证", "text": text}, code=201)
        return self.wait(f"/projects/{project['id']}", "project", "awaiting_direction")

    def version(self, project, target=20000, **options):
        pid = project["project"]["id"]
        body = {"source": "candidate", "candidate_id": project["directions"][0]["id"], "target_words": target, **options}
        version = self.send(f"/projects/{pid}/versions", body, code=201)
        return self.wait(f"/versions/{version['id']}", "version", "awaiting_outline")


def block_review(inputs):
    return json.dumps({"chapters": [{
        "index": c["index"], "verdict": "block",
        "consistency_issues": [{"severity": "high", "quote": "正文里并没有这句", "reason": "铜钥匙位置可能与前文不一致，交编辑核对。", "fix_suggestions": ["问题条目中也可附修改建议。"]}],
        "plan_deviation": [], "pacing_issues": [], "ai_flavor_issues": [],
        "hook_ok": False, "payoff_ok": False, "fix_suggestions": ["核对钥匙位置。"],
    } for c in inputs["context"]["written_chapters"]]}, ensure_ascii=False)


def test_default_twelve_calls_full_context_and_advisory_review(client, monkeypatch):
    from app.llm.gateway import gateway
    from app.llm.structured import parse_output
    from app.models import ChapterPlanRow, LLMCall, StoryBibleSnapshot
    from app.schemas import SourceSummary
    from app.services import rows

    repaired = parse_output('{"synopsis":"雨夜追查", "characters":[{"name":"林舟","role":"主角","description":"拿着钥匙"}], "ending":"门外有声",}', SourceSummary)
    assert repaired.ending == "门外有声"
    original = gateway.complete
    observed = []

    async def complete(name, inputs, messages, project_id, version_id=None):
        observed.append((name, deepcopy(inputs)))
        raw = await original(name, inputs, messages, project_id, version_id)
        return block_review(inputs) if name == "n7_review" else raw

    monkeypatch.setattr(gateway, "complete", complete)
    flow = Workflow(client)
    # Exceed the old 60k context budget, including a fact near the beginning.
    body = "林舟把铜钥匙放进左袋。沈砚在门外等他。\n" + "雨滴沿窗框落下。" * 8200 + "\n原文末尾唯一标记：门开了。"
    assert len(body) > 60000
    project = flow.project("第1章 雨夜\n" + body)
    pid = project["project"]["id"]
    assert project["understanding"]["data"]["characters"]
    assert len(project["directions"]) == 3
    assert len({d["data"]["main_trope"] for d in project["directions"]}) == 3
    assert not any(d["judge_scores"] for d in project["directions"])
    assert not rows(StoryBibleSnapshot, StoryBibleSnapshot.project_id == pid)

    pending = flow.version(project)
    vid = pending["version"]["id"]
    outline = pending["outline"]["data"]
    assert len(outline["chapters"]) == 8
    assert sum(c["target_words"] for c in outline["chapters"]) == 20000
    assert all(c["events"] for c in outline["chapters"])
    flow.send(f"/versions/{vid}/submit", code=409)
    outline["chapters"][0]["events"] = ["编辑确认：钥匙留在林舟左袋。", "当面对质。"]
    flow.send(f"/versions/{vid}/outline", {"outline": outline}, method="PUT")
    flow.send(f"/versions/{vid}/outline/confirm", code=202)
    ready = flow.wait(f"/versions/{vid}", "version", "awaiting_review")
    assert len(ready["chapters"]) == len(ready["draft_history"]) == 8
    counts = Counter(name for name, _ in observed)
    assert counts == {"n1_understand": 1, "n2_directions": 1, "n4_outline": 1, "n6_write_chapter": 8, "n7_review": 1}
    calls = rows(LLMCall, LLMCall.project_id == pid)
    assert len(calls) == 12 and all(c.success and c.prompt_version for c in calls)
    assert not rows(ChapterPlanRow, ChapterPlanRow.version_id == vid)
    assert not rows(StoryBibleSnapshot, StoryBibleSnapshot.project_id == pid)
    writes = [payload["context"] for name, payload in observed if name == "n6_write_chapter"]
    for i, context in enumerate(writes):
        assert context["source_chapters"][0]["content"] == body
        assert context["written_chapters"] == [{k: c[k] for k in ("index", "title", "content")} for c in ready["chapters"][:i]]
        assert context["outline"] == outline
        assert context["plan"]["events"] == outline["chapters"][i]["events"]
        assert "story_bible_brief" not in context
    audit = next(payload["context"] for name, payload in observed if name == "n7_review")
    assert audit["source_chapters"][0]["content"] == body
    assert len(audit["written_chapters"]) == 8
    assert all(r["verdict"] == "block" for r in ready["reviews"])
    assert all(r["llm_review"]["consistency_issues"][0]["quote"] == "正文里并没有这句" for r in ready["reviews"])
    assert all(r["llm_review"]["consistency_issues"][0]["fix_suggestions"] for r in ready["reviews"])
    assert all(not r["editor_accepted"] for r in ready["reviews"])
    assert flow.send(f"/versions/{vid}/submit")["status"] == "submitted"
    text = client.get(f"/api/versions/{vid}/export?format=txt")
    doc = client.get(f"/api/versions/{vid}/export?format=docx")
    assert text.status_code == doc.status_code == 200
    assert body in text.text and "演示数据" in text.text
    assert ready["chapters"][-1]["content"] in text.text
    assert "铜钥匙" in "\n".join(p.text for p in Document(io.BytesIO(doc.content)).paragraphs)


def test_recovery_edit_fulltext_rewrite_and_review_failure(client, monkeypatch):
    from app.llm.gateway import gateway
    from app.models import ChapterDraft
    from app.services import rows

    original = gateway.complete
    observed = []
    fail_write = [True]
    fail_review = [True]

    async def complete(name, inputs, messages, project_id, version_id=None):
        observed.append((name, deepcopy(inputs)))
        if name == "n6_write_chapter" and len(inputs["context"]["written_chapters"]) == 1 and fail_write[0]:
            fail_write[0] = False
            raise RuntimeError("injected write interruption")
        if name == "n7_review" and fail_review[0]:
            fail_review[0] = False
            raise RuntimeError("injected review outage")
        raw = await original(name, inputs, messages, project_id, version_id)
        return block_review(inputs) if name == "n7_review" else raw

    monkeypatch.setattr(gateway, "complete", complete)
    flow = Workflow(client)
    project = flow.project()
    pending = flow.version(project, target=1000)
    vid = pending["version"]["id"]
    flow.send(f"/versions/{vid}/outline/confirm", code=202)
    broken = flow.wait(f"/versions/{vid}", "version", "failed")
    assert len(broken["chapters"]) == 1
    first_id = broken["chapters"][0]["id"]
    first_index = broken["chapters"][0]["index"]
    flow.send(f"/versions/{vid}/retry", code=202)
    ready = flow.wait(f"/versions/{vid}", "version", "awaiting_review")
    assert len(ready["chapters"]) == 5
    assert ready["chapters"][0]["id"] == first_id
    assert len(rows(ChapterDraft, ChapterDraft.version_id == vid, ChapterDraft.index == first_index)) == 1
    assert all(r["verdict"] == "unreviewed" and "injected review outage" in r["llm_review"]["error"] for r in ready["reviews"])
    assert not any(name == "n6_rewrite_chapter" for name, _ in observed)

    flow.send(f"/versions/{vid}/review", code=202)
    reviewed = flow.wait(f"/versions/{vid}", "version", "awaiting_review")
    assert len(reviewed["reviews"]) == 10
    assert len(reviewed["draft_history"]) == 5
    edited_body = "第2章 修订\n\n编辑新事实唯一标记：铜钥匙交到沈砚手里。"
    flow.send(f"/versions/{vid}/chapters/{first_index}", {"content": edited_body}, method="PUT")
    edited = flow.wait(f"/versions/{vid}", "version", "awaiting_review")
    assert len(edited["draft_history"]) == 6
    assert len(edited["version"]["stale_chapters"]) == 4
    current_first = edited["chapters"][0]
    assert current_first["id"] != first_id
    audit = [payload for name, payload in observed if name == "n7_review"][-1]["context"]
    assert audit["written_chapters"][0]["content"] == current_first["content"]
    assert "编辑新事实唯一标记" in audit["written_chapters"][0]["content"]

    second = edited["chapters"][1]
    flow.send(f"/versions/{vid}/chapters/{second['index']}/regenerate", {"instruction": "按编辑修订后的钥匙位置接写。"}, code=202)
    rewritten = flow.wait(f"/versions/{vid}", "version", "awaiting_review")
    rewrites = [payload for name, payload in observed if name == "n6_rewrite_chapter"]
    assert len(rewrites) == 1
    assert rewrites[0]["suggestions"] == ["按编辑修订后的钥匙位置接写。"]
    assert rewrites[0]["context"]["written_chapters"] == [{k: current_first[k] for k in ("index", "title", "content")}]
    assert len(rewritten["draft_history"]) == 7
    assert rewritten["version"]["stale_chapters"]
    # Submission is the editor's decision, even after a failed review and stale hints.
    fail_review[0] = True
    flow.send(f"/versions/{vid}/review", code=202)
    failed_audit = flow.wait(f"/versions/{vid}", "version", "awaiting_review")
    latest = max(failed_audit["reviews"], key=lambda r: r["id"])
    assert latest["verdict"] == "unreviewed"
    assert flow.send(f"/versions/{vid}/submit", {"reason": "编辑已核对"})["status"] == "submitted"
    actions = client.get(f"/api/versions/{vid}").json()["actions"]
    assert {"version_retry", "review_request", "chapter_edit", "chapter_regenerate", "version_submit"} <= {a["action"] for a in actions}
    assert next(a for a in actions if a["action"] == "chapter_regenerate")["payload"]["generated_draft_id"] == rewritten["chapters"][1]["id"]


def test_direction_regeneration_edit_manual_and_logs(client, monkeypatch):
    from app.llm.gateway import gateway
    from app.models import EditorAction
    from app.services import rows

    original = gateway.complete
    invalid_once = [True]
    direction_attempts = []

    async def complete(name, inputs, messages, project_id, version_id=None):
        raw = await original(name, inputs, messages, project_id, version_id)
        if name == "n2_directions":
            direction_attempts.append(deepcopy(inputs))
            if invalid_once[0]:
                invalid_once[0] = False
                payload = json.loads(raw)
                payload["directions"][1]["main_trope"] = payload["directions"][0]["main_trope"]
                return json.dumps(payload, ensure_ascii=False)
        return raw

    monkeypatch.setattr(gateway, "complete", complete)
    flow = Workflow(client)
    project = flow.project()
    pid = project["project"]["id"]
    assert len(direction_attempts) == 2
    old = project["directions"][0]
    flow.send(f"/projects/{pid}/directions/regenerate", {"reason": "想换一批"}, code=202)
    current = flow.wait(f"/projects/{pid}", "project", "awaiting_direction")
    assert current["project"]["active_batch"] != project["project"]["active_batch"]
    assert direction_attempts[-1]["avoid"]
    flow.send(f"/projects/{pid}/versions", {"source": "candidate", "candidate_id": old["id"]}, code=422)
    flow.send(f"/projects/{pid}/versions", {"source": "auto"}, code=422)

    chosen = current["directions"][0]
    direction = deepcopy(chosen["data"])
    direction["main_trope"] = "编辑自定义主套路"
    direction["continuation_start"] = "从原文开门的动作接起，先追问钥匙。"
    edited = flow.version(current, target=1000, source="edited", candidate_id=chosen["id"], direction=direction, reason="强化冲突")
    edit_actions = edited["actions"]
    action = next(a for a in edit_actions if a["action"] == "direction_edit")
    assert action["payload"]["before"] == chosen["data"]
    assert action["payload"]["after"] == direction
    assert action["payload"]["displayed_candidate_ids"] == [d["id"] for d in current["directions"]]

    manual_text = "沈砚当面还回铜钥匙，让林舟主动公开账册。"
    manual = flow.send(f"/projects/{pid}/versions", {"source": "manual", "manual_text": manual_text, "target_words": 1000}, code=201)
    confirmed = flow.wait(f"/versions/{manual['id']}", "version", "awaiting_direction_confirmation")
    assert confirmed["outline"] is None
    assert confirmed["version"]["direction"]["continuation_start"]
    flow.send(f"/versions/{manual['id']}/direction/confirm", code=202)
    normalized = flow.wait(f"/versions/{manual['id']}", "version", "awaiting_outline")
    assert normalized["outline"]
    actions = rows(EditorAction, EditorAction.project_id == pid)
    assert {"direction_reject", "direction_regenerate", "direction_edit", "direction_select", "direction_manual", "direction_confirm"} <= {a.action for a in actions}
    assert next(a for a in actions if a.action == "direction_manual").payload["after"]["manual_text"] == manual_text
