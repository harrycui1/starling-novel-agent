"""One workflow test: real DB/API/state machine, deterministic LLM, no network."""
import time

from fastapi.testclient import TestClient


def test_editor_workflow_and_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_DATABASE_URL", f"sqlite:///{tmp_path / 'smoke.db'}")
    monkeypatch.setenv("NOVEL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NOVEL_MODE", "demo")
    from app.main import app
    from app.llm.gateway import gateway
    from app.llm.structured import parse_output
    from app.schemas import Digest
    from app.models import ChapterDraft
    from app.services import rows

    assert parse_output('```json\n{"chapter":1,"title":"雨夜","digest":"线索",}\n```', Digest).chapter == 1
    original_complete = gateway.complete
    fail_patch_once = [True]
    bad_digest_once = [True]

    async def complete(name, inputs, messages, project_id, version_id=None):
        if name == "n1_chapter_digest" and bad_digest_once[0]:
            bad_digest_once[0] = False
            return '{"chapter":"invalid"}'
        if name == "n6_bible_update" and fail_patch_once[0]:
            fail_patch_once[0] = False
            raise RuntimeError("injected interruption after draft persistence")
        return await original_complete(name, inputs, messages, project_id, version_id)
    monkeypatch.setattr(gateway, "complete", complete)

    with TestClient(app) as client:
        def send(path, data=None, method="POST", code=200):
            response = client.request(method, "/api" + path, json=data or {})
            assert response.status_code == code, response.text
            return response.json()

        def wait(path, kind, wanted):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                result = client.get("/api" + path).json()
                status = result[kind]["status"]
                if status == wanted:
                    return result
                if status == "failed" and wanted != "failed":
                    raise AssertionError(result[kind]["error"])
                time.sleep(.02)
            raise AssertionError(f"timed out: {result}")

        from pathlib import Path
        source = Path("examples/雨夜账册.txt").read_text()
        project = send("/projects", {"title": "冒烟样例", "text": source, "genre_tags": ["悬疑"]}, code=201)
        pid = project["id"]
        ready = wait(f"/projects/{pid}", "project", "awaiting_direction")
        assert len(ready["directions"]) == 3
        assert len({d["data"]["main_trope"] for d in ready["directions"]}) == 3
        version = send(f"/projects/{pid}/versions", {"source": "candidate", "candidate_id": ready["directions"][0]["id"], "target_words": 1000}, code=201)
        vid = version["id"]
        outline = wait(f"/versions/{vid}", "version", "awaiting_outline")
        assert len(outline["outline"]["data"]["chapters"]) == 5
        send(f"/versions/{vid}/submit", code=409)
        send(f"/versions/{vid}/outline", {"outline": outline["outline"]["data"]}, method="PUT")
        send(f"/versions/{vid}/outline/confirm", code=202)
        broken = wait(f"/versions/{vid}", "version", "failed")
        assert len(broken["chapters"]) == 1
        first_id = broken["chapters"][0]["id"]
        send(f"/versions/{vid}/retry", code=202)
        review = wait(f"/versions/{vid}", "version", "awaiting_review")
        assert len(review["chapters"]) == 5
        assert review["chapters"][0]["id"] == first_id
        assert len(rows(ChapterDraft, ChapterDraft.version_id == vid, ChapterDraft.index == review["chapters"][0]["index"])) == 1
        first = review["chapters"][0]
        send(f"/versions/{vid}/chapters/{first['index']}", {"content": first["content"] + "\n雨停了。"}, method="PUT")
        edited = wait(f"/versions/{vid}", "version", "awaiting_review")
        assert len(edited["draft_history"]) == 6
        assert len(edited["version"]["stale_chapters"]) == 4
        send(f"/versions/{vid}/submit", code=409)
        for chapter in edited["chapters"]:
            send(f"/versions/{vid}/chapters/{chapter['index']}/accept")
        assert send(f"/versions/{vid}/submit")["status"] == "submitted"
        text = client.get(f"/api/versions/{vid}/export?format=txt")
        doc = client.get(f"/api/versions/{vid}/export?format=docx")
        assert "演示数据" in text.text and "雨停了" in text.text
        assert doc.content.startswith(b"PK")
        actions = client.get(f"/api/versions/{vid}").json()["actions"]
        assert {"direction_select", "outline_edit", "outline_confirm", "chapter_edit", "version_submit"} <= {a["action"] for a in actions}
        manual = send(f"/projects/{pid}/versions", {"source":"manual", "manual_text":"核对账册，让真相公开", "target_words":1000}, code=201)
        wait(f"/versions/{manual['id']}", "version", "awaiting_direction_confirmation")
        send(f"/versions/{manual['id']}/direction/confirm", code=202)
        wait(f"/versions/{manual['id']}", "version", "awaiting_outline")
