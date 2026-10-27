import math
from collections import Counter
from itertools import combinations

from app.checks import similarity
from app.models import ChapterDraft, ChapterReview, DirectionCandidate, LLMCall, Version
from app.services import rows, current_drafts, one


def report(version_id):
    version = one(Version, version_id)
    if not version:
        raise ValueError("找不到版本")
    drafts = rows(ChapterDraft, ChapterDraft.version_id == version_id)
    reviews = rows(ChapterReview, ChapterReview.draft_id.in_([d.id for d in drafts]))
    first = [d for d in drafts if d.rev == 0]
    latest_by_draft = {}
    for row in sorted(reviews, key=lambda row: row.id):
        latest_by_draft[row.draft_id] = row
    first_reviews = [latest_by_draft[d.id] for d in first if d.id in latest_by_draft]
    selected = current_drafts(version_id)
    latest_reviews = [max([r for r in reviews if r.draft_id == d.id], key=lambda r: r.id) for d in selected if any(r.draft_id == d.id for r in reviews)]
    calls = rows(LLMCall, (LLMCall.version_id == version_id) | ((LLMCall.project_id == version.project_id) & (LLMCall.version_id == None)))
    candidates = rows(DirectionCandidate, DirectionCandidate.project_id == version.project_id, DirectionCandidate.shortlisted == True)
    chosen = one(DirectionCandidate, version.direction_candidate_id) if version.direction_candidate_id else None
    if chosen:
        candidates = [c for c in candidates if c.batch_id == chosen.batch_id]
    pairs = [similarity(a.data["synopsis"], b.data["synopsis"]) for a, b in combinations(candidates, 2)]
    distribution = Counter(v.direction.get("main_trope", "未定") for v in rows(Version))
    total_versions = sum(distribution.values())
    total_words = sum(d.word_count for d in selected)
    high = sum(1 for r in latest_reviews for issue in r.llm_review.get("consistency_issues", []) if issue["severity"] == "high")
    from app.services import latest_plans
    targets = {p.index: p.data["target_words"] for p in latest_plans(version_id)}
    deviations = [abs(d.word_count - targets[d.index]) / targets[d.index] for d in selected if d.index in targets]
    by_prompt = {}
    for call in calls:
        metrics = by_prompt.setdefault(call.prompt_name, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0})
        metrics["calls"] += 1
        metrics["input_tokens"] += call.input_tokens
        metrics["output_tokens"] += call.output_tokens
        metrics["latency_ms"] += call.latency_ms
    prompt_versions = {}
    for c in calls:
        prompt_versions.setdefault(c.prompt_name, set()).add(c.prompt_version)
    return {"version_id": version_id, "status": version.status, "words": total_words, "chapters": len(selected), "planned_chapters": version.total_chapters, "completion_rate": len(selected) / max(version.total_chapters, 1), "mean_length_deviation": sum(deviations) / max(len(deviations), 1), "first_draft_actionable_rule_issue_rate": sum(any(i["verdict"] in {"revise", "block"} for i in r.rule_issues) for r in first_reviews) / max(len(first_reviews), 1), "calls_by_prompt": by_prompt, "consistency_errors_per_10k": high * 10000 / max(total_words, 1), "first_draft_pass_rate": sum(r.verdict == "pass" for r in first_reviews) / max(len(first_reviews), 1), "first_draft_rule_issue_rate": sum(bool(r.rule_issues) for r in first_reviews) / max(len(first_reviews), 1), "mean_ai_rewrites": sum(d.rev > 0 and d.author == "ai" for d in drafts) / max(len(selected), 1), "direction_similarity_mean": sum(pairs) / max(len(pairs), 1), "trope_entropy": -sum((n / total_versions) * math.log2(n / total_versions) for n in distribution.values()), "input_tokens": sum(c.input_tokens for c in calls), "output_tokens": sum(c.output_tokens for c in calls), "model_latency_ms": sum(c.latency_ms for c in calls), "failed_calls": sum(not c.success for c in calls), "prompt_versions": {k: sorted(v) for k, v in prompt_versions.items()}, "notes": ["token含本项目共享的原文理解和方向生成调用，跨版本对比时请注意共享成本。", "一致性错误为模型判定，需人工校准；未配置单价，不估算费用。"]}
