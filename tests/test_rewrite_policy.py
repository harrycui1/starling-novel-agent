import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock


def review(verdict="pass", issues=None):
    from app.schemas import ReviewResult
    return ReviewResult(verdict=verdict, consistency_issues=issues or [], plan_deviation=[], pacing_issues=[], ai_flavor_issues=[], hook_ok=True, payoff_ok=True, fix_suggestions=[])


def test_only_explicit_model_block_stops_rewriting():
    from app.checks import merge_verdict
    from app.schemas import Issue
    high = Issue(severity="high", quote="铜钥匙", reason="道具位置前后不一致")
    assert merge_verdict([], review(issues=[high])) == "revise"
    assert merge_verdict([{"verdict": "info"}], review()) == "pass"
    assert merge_verdict([{"verdict": "block"}], review()) == "revise"
    assert merge_verdict([], review("block")) == "block"


def test_bad_quote_is_discarded_without_losing_valid_review():
    from app.pipeline.nodes.n6_write import filter_review_quotes
    from app.schemas import Issue
    result, warnings = filter_review_quotes(review(issues=[Issue(severity="high", quote="铜钥匙", reason="检查位置"), Issue(severity="mid", quote="不存在的引文", reason="不能采用")]), "铜钥匙压在账页上。")
    assert [i.quote for i in result.consistency_issues] == ["铜钥匙"]
    assert warnings and warnings[0]["verdict"] == "info"


def test_recoverable_high_issue_reaches_writer(monkeypatch):
    from app.pipeline.nodes import n6_write
    from app.schemas import Issue
    plan = SimpleNamespace(index=3, title="账册")
    draft = SimpleNamespace(id=1, index=3, rev=0, content="第3章 账册\n铜钥匙压在账页上。")
    monkeypatch.setattr(n6_write, "build_write_context", lambda *a: {})
    monkeypatch.setattr(n6_write, "build_review_context", lambda *a: {})
    monkeypatch.setattr(n6_write, "draft_issues", lambda *a: [])
    monkeypatch.setattr(n6_write, "rows", lambda *a, **kw: [])
    monkeypatch.setattr(n6_write, "save", lambda *a: None)
    monkeypatch.setattr(n6_write, "structured", AsyncMock(side_effect=[review(issues=[Issue(severity="high", quote="铜钥匙", reason="应在桌上")]), review()]))
    writer = AsyncMock(return_value="铜钥匙仍压在账页上。")
    monkeypatch.setattr(n6_write.gateway, "complete", writer)
    monkeypatch.setattr(n6_write, "store_draft", lambda *a: SimpleNamespace(id=2, index=3, rev=1, content=a[3]))
    result = asyncio.run(n6_write.write_one(SimpleNamespace(project_id=1, version_id=1), plan, object(), existing=draft))
    assert result.rev == 1 and writer.await_count == 1


def test_old_model_block_gets_a_fresh_review(monkeypatch):
    from app.pipeline.nodes import n6_write
    old = SimpleNamespace(llm_review=review("block").model_dump())
    monkeypatch.setattr(n6_write, "rows", lambda *a, **kw: [old])
    assert n6_write.current_review(object(), SimpleNamespace(id=1), object(), object()) is None
