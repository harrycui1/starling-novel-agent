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
    first_reviews = [r for r in reviews if r.draft_id in {d.id for d in first}]
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
    prompt_versions = {}
    for c in calls:
        prompt_versions.setdefault(c.prompt_name, set()).add(c.prompt_version)
    return {"version_id": version_id, "status": version.status, "words": total_words, "chapters": len(selected), "consistency_errors_per_10k": high * 10000 / max(total_words, 1), "first_draft_pass_rate": sum(r.verdict == "pass" for r in first_reviews) / max(len(first_reviews), 1), "first_draft_rule_issue_rate": sum(bool(r.rule_issues) for r in first_reviews) / max(len(first_reviews), 1), "mean_ai_rewrites": sum(d.rev > 0 and d.author == "ai" for d in drafts) / max(len(selected), 1), "direction_similarity_mean": sum(pairs) / max(len(pairs), 1), "trope_entropy": -sum((n / total_versions) * math.log2(n / total_versions) for n in distribution.values()), "input_tokens": sum(c.input_tokens for c in calls), "output_tokens": sum(c.output_tokens for c in calls), "model_latency_ms": sum(c.latency_ms for c in calls), "failed_calls": sum(not c.success for c in calls), "prompt_versions": {k: sorted(v) for k, v in prompt_versions.items()}, "notes": ["token含本项目共享的原文理解和方向生成调用，跨版本对比时请注意共享成本。", "一致性错误为模型判定，需人工校准；未配置单价，不估算费用。"]}
