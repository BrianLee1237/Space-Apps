import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

from filelock import FileLock

from .archive import CapacityError
from .config import Settings


def digest(value: str | bytes):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()[:24]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def atomic_write(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.data_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, kind: str, identifier: str, suffix=".json"):
        if not re.fullmatch(r"[a-f0-9]{24}", identifier):
            raise KeyError(identifier)
        folder = self.root / kind
        folder.mkdir(parents=True, exist_ok=True)
        return folder / (identifier + suffix)

    def read(self, kind, identifier):
        try:
            return json.loads(self.path(kind, identifier).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise KeyError(identifier) from exc

    def write(self, kind, identifier, value):
        content = canonical(value).encode()
        self.write_bytes(self.path(kind, identifier), content)

    def write_bytes(self, path, content):
        # Serialize writes across threads/processes; never silently evict scientific products.
        with FileLock(str(self.root / "budget.lock"), timeout=30):
            used = sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())
            previous = path.stat().st_size if path.exists() else 0
            if used - previous + len(content) > self.settings.cache_budget_bytes:
                raise CapacityError(
                    "Local cache budget reached; archive data have not been deleted"
                )
            atomic_write(path, content)

    def cached_search(self, query_key):
        try:
            pointer = self.read("queries", query_key)
            if time.time() - pointer["created_unix"] < self.settings.search_ttl_seconds:
                return self.read("searches", pointer["search_id"])
        except KeyError:
            pass
        return None
