"""Initial editor pipeline schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Frozen migration: future model changes must use a new revision.
    tables = {
        "project": [("title", sa.String(), False), ("genre_tags", sa.JSON(), False), ("channel", sa.String(), False), ("source_word_count", sa.Integer(), False), ("created_by", sa.String(), False), ("created_at", sa.DateTime(), False), ("status", sa.String(), False), ("current_node", sa.String(), False), ("error", sa.String(), True), ("active_batch", sa.String(), True), ("is_demo", sa.Boolean(), False)],
        "version": [("project_id", sa.Integer(), False), ("direction_source", sa.String(), False), ("direction_candidate_id", sa.Integer(), True), ("direction", sa.JSON(), False), ("target_words", sa.Integer(), False), ("status", sa.String(), False), ("current_node", sa.String(), False), ("current_chapter", sa.Integer(), False), ("total_chapters", sa.Integer(), False), ("error", sa.String(), True), ("stale_chapters", sa.JSON(), False), ("online_metrics", sa.JSON(), False), ("created_at", sa.DateTime(), False)],
        "sourcechapter": [("project_id", sa.Integer(), False), ("index", sa.Integer(), False), ("title", sa.String(), False), ("content", sa.String(), False)],
        "storybiblesnapshot": [("project_id", sa.Integer(), False), ("version_id", sa.Integer(), True), ("after_chapter", sa.Integer(), False), ("data", sa.JSON(), False), ("warnings", sa.JSON(), False), ("created_at", sa.DateTime(), False)],
        "directioncandidate": [("project_id", sa.Integer(), False), ("batch_id", sa.String(), False), ("data", sa.JSON(), False), ("judge_scores", sa.JSON(), False), ("shortlisted", sa.Boolean(), False), ("score", sa.Float(), False)],
        "outlinerevision": [("version_id", sa.Integer(), False), ("rev", sa.Integer(), False), ("data", sa.JSON(), False), ("author", sa.String(), False), ("confirmed", sa.Boolean(), False), ("warnings", sa.JSON(), False)],
        "chapterplanrow": [("version_id", sa.Integer(), False), ("index", sa.Integer(), False), ("generation", sa.Integer(), False), ("data", sa.JSON(), False)],
        "chapterdraft": [("version_id", sa.Integer(), False), ("index", sa.Integer(), False), ("rev", sa.Integer(), False), ("title", sa.String(), False), ("content", sa.String(), False), ("word_count", sa.Integer(), False), ("author", sa.String(), False), ("is_current", sa.Boolean(), False)],
        "chapterreview": [("draft_id", sa.Integer(), False), ("verdict", sa.String(), False), ("rule_issues", sa.JSON(), False), ("llm_review", sa.JSON(), False), ("editor_accepted", sa.Boolean(), False)],
        "editoraction": [("project_id", sa.Integer(), False), ("version_id", sa.Integer(), True), ("editor", sa.String(), False), ("action", sa.String(), False), ("payload", sa.JSON(), False), ("created_at", sa.DateTime(), False)],
        "llmcall": [("project_id", sa.Integer(), False), ("version_id", sa.Integer(), True), ("node", sa.String(), False), ("prompt_name", sa.String(), False), ("prompt_version", sa.String(), False), ("model", sa.String(), False), ("input_tokens", sa.Integer(), False), ("output_tokens", sa.Integer(), False), ("latency_ms", sa.Integer(), False), ("success", sa.Boolean(), False), ("error", sa.String(), True), ("raw_output_path", sa.String(), True), ("created_at", sa.DateTime(), False)],
        "pipelineevent": [("project_id", sa.Integer(), False), ("version_id", sa.Integer(), True), ("kind", sa.String(), False), ("data", sa.JSON(), False), ("created_at", sa.DateTime(), False)],
    }
    refs = {"project_id": "project.id", "version_id": "version.id", "direction_candidate_id": "directioncandidate.id", "draft_id": "chapterdraft.id"}
    uniques = {"sourcechapter": ("project_id", "index"), "outlinerevision": ("version_id", "rev"), "chapterdraft": ("version_id", "index", "rev")}
    # Candidates precede versions because versions reference them.
    order = ["project", "sourcechapter", "directioncandidate", "version", "storybiblesnapshot", "outlinerevision", "chapterplanrow", "chapterdraft", "chapterreview", "editoraction", "llmcall", "pipelineevent"]
    for name in order:
        columns = [sa.Column("id", sa.Integer(), primary_key=True)]
        for field, kind, nullable in tables[name]:
            columns.append(sa.Column(field, kind, *([sa.ForeignKey(refs[field])] if field in refs else []), nullable=nullable))
        if name in uniques:
            columns.append(sa.UniqueConstraint(*uniques[name]))
        op.create_table(name, *columns)
        for field, _, _ in tables[name]:
            if field in {"project_id", "version_id", "draft_id"}:
                op.create_index(f"ix_{name}_{field}", name, [field])


def downgrade():
    for name in ["pipelineevent", "llmcall", "editoraction", "chapterreview", "chapterdraft", "chapterplanrow", "outlinerevision", "storybiblesnapshot", "version", "directioncandidate", "sourcechapter", "project"]:
        op.drop_table(name)
