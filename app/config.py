from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Connection(BaseModel):
    protocol: Literal["chat", "responses", "modelhub"] = "chat"
    endpoint: str
    model: str
    api_key_env: str
    parameters: dict = Field(default_factory=dict)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVEL_", env_file=ROOT / ".env", extra="ignore")
    database_url: str = f"sqlite:///{ROOT / 'data/novel.db'}"
    data_dir: Path = ROOT / "data"
    mode: Literal["live", "demo"] = "live"
    connections: dict[str, Connection] = Field(default_factory=dict)
    models: dict[str, str] = Field(default_factory=lambda: dict.fromkeys(["extractor", "planner", "writer", "judge"], "default"))
    target_words: int = 20000
    channels: dict[str, dict[str, int]] = Field(default_factory=lambda: {"default": {"chapter_words": 2500}})
    min_chapters: int = 5
    max_chapters: int = 12
    n2_candidates: int = 8
    n2_shortlist: int = 3
    n2_dedup_threshold: float = 0.6
    n2_recent_window_days: int = 30
    trope_vocab: list[str] = Field(default_factory=lambda: ["打脸", "逆袭", "复仇", "掉马", "追妻", "揭秘", "升级", "救赎", "宅斗", "权谋"])
    judge_weights: dict[str, float] = Field(default_factory=lambda: {"consistency": .3, "payoff_strength": .25, "capacity": .15, "novelty": .15, "channel_fit": .15})
    max_gap_between_payoffs: int = 2
    max_rewrite: int = 2
    word_tolerance: float = .2
    dialogue_ratio_tolerance: float = .10
    context_budget_tokens: int = 60000
    max_parallel_versions: int = 4
    structured_max_retry: int = 2
    request_retries: int = 2
    request_timeout: float = 600
    banned_word_threshold: int = 3
    banned_endings_file: Path = ROOT / "app/checks/data/banned_endings.txt"
    banned_words_file: Path = ROOT / "app/checks/data/banned_words.txt"


settings = Settings()
