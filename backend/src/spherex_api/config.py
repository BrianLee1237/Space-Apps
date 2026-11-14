"""Configuration contains no secrets; archive access is anonymous HTTPS."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    timeout_seconds: float = 120
    retries: int = 2
    search_ttl_seconds: int = 900
    max_response_bytes: int = 32 * 1024 * 1024
    archive_concurrency: int = 4
    cache_budget_bytes: int = 2 * 1024 * 1024 * 1024

    @classmethod
    def from_env(cls):
        return cls(
            data_dir=Path(os.getenv("SPHEREX_DATA_DIR", "data")).resolve(),
            timeout_seconds=float(os.getenv("SPHEREX_TIMEOUT_SECONDS", "120")),
            cache_budget_bytes=int(os.getenv("SPHEREX_CACHE_BUDGET_MB", "2048")) * 1024**2,
        )
