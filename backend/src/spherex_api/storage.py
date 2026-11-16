import hashlib
import json
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

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
        # Walked once at startup; write_bytes() then keeps this current in
        # memory instead of re-walking the whole cache tree on every write.
        # Assumes one process owns this data_dir (true for the documented
        # single uvicorn-process deployment); a multi-worker deployment
        # sharing one data_dir would need a cross-process counter instead.
        self._used_bytes = sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())
        self._pins = {}
        self._pin_lock = threading.RLock()

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
            previous = path.stat().st_size if path.exists() else 0
            self._evict(
                max(
                    0, self._used_bytes - previous + len(content) - self.settings.cache_budget_bytes
                ),
                path,
            )
            if self._used_bytes - previous + len(content) > self.settings.cache_budget_bytes:
                raise CapacityError(
                    "Local cache budget reached; archive data have not been deleted"
                )
            atomic_write(path, content)
            self._used_bytes += len(content) - previous

    @contextmanager
    def pin(self, identifiers):
        frames = {identifier.split(".")[-1] for identifier in identifiers}
        with self._pin_lock:
            for frame in frames:
                self._pins[frame] = self._pins.get(frame, 0) + 1
        try:
            yield
        finally:
            with self._pin_lock:
                for frame in frames:
                    self._pins[frame] -= 1
                    if not self._pins[frame]:
                        del self._pins[frame]

    def _evict(self, required, writing):
        """Evict only idle generated previews and downloaded cutouts.

        Search manifests, evidence databases, reports, arbitrary user files, active
        jobs, and recently accessed exposures are retained. Eviction takes the
        same frame lock as download, with a non-blocking timeout.
        """
        if required <= 0:
            return
        candidates = []
        for kind, suffix in (("previews", ".png"), ("cutouts", ".fits")):
            candidates.extend((self.root / kind).glob("*" + suffix))
        candidates.sort(key=lambda item: item.stat().st_mtime)
        freed = 0
        for candidate in candidates:
            if candidate == writing or not re.fullmatch(r"[a-f0-9]{24}", candidate.stem):
                continue
            with self._pin_lock:
                if candidate.stem in self._pins:
                    continue
                try:
                    with FileLock(str(candidate) + ".lock", timeout=0):
                        if not candidate.exists() or time.time() - candidate.stat().st_mtime < 120:
                            continue
                        size = candidate.stat().st_size
                        candidate.unlink()
                        freed += size
                        if candidate.suffix == ".fits":
                            metadata = self.path("metadata", candidate.stem)
                            if metadata.exists():
                                size = metadata.stat().st_size
                                metadata.unlink()
                                freed += size
                except (Timeout, OSError):
                    continue
            if freed >= required:
                break
        self._used_bytes = max(0, self._used_bytes - freed)

    def statistics(self):
        return {
            "usedBytes": self._used_bytes,
            "budgetBytes": self.settings.cache_budget_bytes,
            "policy": "Idle temporary previews and downloaded FITS, least-recently-used first",
            "protected": "Evidence, reports, search manifests, active jobs, and recent exposures",
        }

    def cached_search(self, query_key):
        try:
            pointer = self.read("queries", query_key)
            if time.time() - pointer["created_unix"] < self.settings.search_ttl_seconds:
                return self.read("searches", pointer["search_id"])
        except KeyError:
            pass
        return None
