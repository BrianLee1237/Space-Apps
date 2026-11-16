import io
import json
import threading
import time
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from filelock import FileLock

from .archive import ArchiveClient, ArchiveError, cutout_url
from .config import Settings
from .imaging import full_sha256, inspect_fits
from .models import SearchRequest
from .storage import Store, canonical, digest
from .targets import TARGETS

METADATA_SCHEMA_VERSION = 1


class SkyService:
    def __init__(self, settings: Settings, archive=None):
        self.settings = settings
        self.store = Store(settings)
        self.archive = archive or ArchiveClient(settings)
        self._manifest_cache = lru_cache(maxsize=128)(
            lambda search_id: self.store.read("searches", search_id)
        )
        self._search_unavailable_until = 0
        self._search_error = "IRSA discovery is temporarily unavailable"
        self._availability_lock = threading.Lock()
        self._availability = None
        self._availability_until = 0
        self._reference_searches = json.loads(
            Path(__file__).with_name("reference_fields.json").read_text(encoding="utf-8")
        )["searches"]

    def discovery_snapshots(self):
        for pointer in (self.store.root / "queries").glob("*.json"):
            manifest = self.store.cached_search(pointer.stem, allow_stale=True)
            if manifest:
                yield manifest
        yield from self._reference_searches

    def availability(self):
        with self._availability_lock:
            if self._availability and time.monotonic() < self._availability_until:
                return self._availability
            available = self.archive.discovery_available()
            self._availability = {
                "discoveryAvailable": available,
                "checkedAt": datetime.now(UTC).isoformat(),
                "savedFields": self.saved_fields(),
            }
            self._availability_until = time.monotonic() + 60
            if available:
                self._search_unavailable_until = 0
            else:
                self._search_unavailable_until = time.monotonic() + 60
            return self._availability

    def saved_fields(self):
        fields = {}
        defaults = SearchRequest(ra=0, dec=0)
        for manifest in self.discovery_snapshots():
            try:
                if not manifest or not manifest["frames"] or not manifest["complete"]:
                    continue
                query = SearchRequest.model_validate(manifest["query"])
                if query.coverage != "center" or query.collections != defaults.collections:
                    continue
                if query.mjd_min is not None or query.mjd_max is not None:
                    continue
                if query.max_records != defaults.max_records:
                    continue
                key = (round(query.ra, 8), round(query.dec, 8))
                if key not in fields:
                    target = next(
                        (
                            target
                            for target in TARGETS
                            if round(target["ra"], 8) == key[0]
                            and round(target["dec"], 8) == key[1]
                        ),
                        None,
                    )
                    fields[key] = {
                        "name": target["name"]
                        if target
                        else f"RA {query.ra:.5f}, Dec {query.dec:.5f}",
                        "raDeg": query.ra,
                        "decDeg": query.dec,
                        "fovArcmin": target["fov_arcmin"] if target else query.fov_arcmin,
                        "detectors": set(),
                    }
                fields[key]["detectors"].update(frame["detector"] for frame in manifest["frames"])
            except (KeyError, ValueError, TypeError):
                continue
        return [
            {**field, "detectors": sorted(field["detectors"])}
            for field in sorted(fields.values(), key=lambda item: item["name"])
            if 6 in field["detectors"]
        ]

    @staticmethod
    def query_key(request):
        values = request.model_dump(mode="json")
        # SIA itself uses eight decimal places. Equivalent browser/Python float
        # serialization should share the same search and downloaded cutouts.
        for coordinate in ("ra", "dec", "fov_arcmin"):
            values[coordinate] = round(values[coordinate], 8)
        return digest(canonical(values))

    def cached_snapshot(self, request, key):
        cached = self.store.cached_search(key, allow_stale=True)
        if cached:
            return cached
        matches, compatible = [], []
        for manifest in self.discovery_snapshots():
            try:
                if not manifest:
                    continue
                previous = SearchRequest.model_validate(manifest["query"])
                if self.query_key(previous) == key:
                    matches.append(manifest)
                elif request.coverage == previous.coverage == "center":
                    adjusted = previous.model_copy(
                        update={
                            "fov_arcmin": request.fov_arcmin,
                            "detectors": request.detectors,
                        }
                    )
                    if (
                        set(request.detectors).issubset(previous.detectors)
                        and self.query_key(adjusted) == key
                    ):
                        compatible.append(manifest)
            except (KeyError, ValueError):
                continue
        if matches:
            source = max(matches, key=lambda item: item["created_at_utc"])
            if not source.get("reference_snapshot"):
                return source
            return self.save_snapshot(
                request,
                key,
                [dict(frame) for frame in source["frames"]],
                not source["complete"],
                source["archive_rows_returned"],
                source["upstream_query_parameters"],
                created_at=source["created_at_utc"],
                extra_warnings=[
                    f"Using bundled IRSA discovery metadata for {source['target_name']}, "
                    f"retrieved {source['created_at_utc']}. Native images are downloaded from IRSA."
                ],
            )
        if not compatible:
            return None
        source = max(compatible, key=lambda item: item["created_at_utc"])
        frames = [
            {**frame, "cutout_url": cutout_url(frame["access_url"], request)}
            for frame in source["frames"]
            if frame["detector"] in request.detectors
        ]
        return self.save_snapshot(
            request,
            key,
            frames,
            not source["complete"],
            source["archive_rows_returned"],
            source["upstream_query_parameters"],
            created_at=source["created_at_utc"],
            extra_warnings=[
                f"Reused discovery metadata from saved search {source['search_id']} "
                "at the same sky center. Field size changes request new native FITS cutouts.",
            ],
        )

    def search(self, request: SearchRequest, refresh=False):
        key = self.query_key(request)
        lock = self.store.path("queries", key, ".lock")
        with FileLock(str(lock), timeout=180):
            cached = self.cached_snapshot(request, key)
            if cached and not refresh:
                age = time.time() - datetime.fromisoformat(cached["created_at_utc"]).timestamp()
                if age < self.settings.search_ttl_seconds:
                    return {**cached, "cache_hit": True, "stale": False}
            try:
                if not refresh and time.monotonic() < self._search_unavailable_until:
                    raise ArchiveError(self._search_error)
                frames, overflow, upstream_count, params = self.archive.search(request)
                self._search_unavailable_until = 0
            except ArchiveError as exc:
                self._availability_until = 0
                self._search_error = str(exc)
                self._search_unavailable_until = time.monotonic() + 30
                if cached:
                    return {
                        **cached,
                        "cache_hit": True,
                        "stale": True,
                        "warnings": [
                            *cached["warnings"],
                            "Live dated-image discovery is unavailable. "
                            "Using the saved search from "
                            f"{cached['created_at_utc']}. New observations may be absent. "
                            "Search again when live discovery is available.",
                        ],
                    }
                raise ArchiveError(
                    f"{exc}. No saved observations cover this exact search yet. "
                    "Retry shortly or open a previously loaded field."
                ) from exc
            return self.save_snapshot(request, key, frames, overflow, upstream_count, params)

    def save_snapshot(
        self,
        request,
        key,
        frames,
        overflow,
        upstream_count,
        params,
        created_at=None,
        extra_warnings=(),
    ):
        warnings = [
            "Frames are sorted by observation MJD, not file processing DATE.",
            "Wavelength coverage in the manifest describes the detector, not the target pixel.",
            "Select comparable wavelengths before interpreting time variability.",
        ]
        if request.coverage == "center":
            warnings.append(
                "Discovery uses a 1 arcsec circle at the field center. "
                "Use coverage=field to include images overlapping only the outer field."
            )
        if overflow:
            warnings.append(
                "Search may be truncated before detector filtering. Narrow the time range "
                "or increase max_records; this is not a complete chronological sequence."
            )
        warnings.extend(extra_warnings)
        now = created_at or datetime.now(UTC).isoformat()
        for frame in frames:
            frame["frame_id"] = digest(frame["cutout_url"])
        search_id = digest(key + now + canonical(frames))
        for frame in frames:
            base = f"/v1/searches/{search_id}/frames/{frame['frame_id']}"
            frame["links"] = {
                "metadata": base,
                "fits": base + "/fits",
                "preview": base + "/preview.png",
            }
        manifest = {
            "search_id": search_id,
            "created_at_utc": now,
            "query": request.model_dump(mode="json"),
            "complete": not overflow,
            "archive_rows_returned": upstream_count,
            "frame_count": len(frames),
            "mjd_min": frames[0]["mjd_start"] if frames else None,
            "mjd_max": frames[-1]["mjd_start"] if frames else None,
            "source": "NASA/IPAC IRSA SPHEREx SIA2",
            "search_radius_deg": request.radius_deg,
            "upstream_query_parameters": params,
            "warnings": warnings,
            "frames": frames,
        }
        self.store.write("searches", search_id, manifest)
        self.store.write(
            "queries",
            key,
            {"search_id": search_id, "created_unix": datetime.fromisoformat(now).timestamp()},
        )
        return {**manifest, "cache_hit": False}

    def manifest(self, search_id):
        return self._manifest_cache(search_id)

    def frame(self, search_id, frame_id):
        manifest = self.manifest(search_id)
        frame = next((f for f in manifest["frames"] if f["frame_id"] == frame_id), None)
        if frame is None:
            raise KeyError(frame_id)
        path = self.store.path("cutouts", frame_id, ".fits")
        with FileLock(str(path) + ".lock", timeout=180):
            if path.exists():
                try:
                    metadata = self.store.read("metadata", frame_id)
                    if metadata.get("metadata_schema_version") == METADATA_SCHEMA_VERSION:
                        checksum = full_sha256(path.read_bytes())
                        if checksum == metadata.get("sha256"):
                            path.touch()
                            return path, {**frame, **metadata}
                        self.store.discard_frame(frame_id)
                except (KeyError, ValueError):
                    pass
            request = SearchRequest.model_validate(manifest["query"])
            if path.exists():
                payload = path.read_bytes()
            else:
                payload = self.archive.fetch(frame["cutout_url"])
            try:
                metadata = inspect_fits(io.BytesIO(payload), request)
            except (ArchiveError, OSError, ValueError, KeyError, IndexError) as exc:
                if path.exists():
                    self.store.discard_frame(frame_id)
                    payload = self.archive.fetch(frame["cutout_url"])
                    try:
                        metadata = inspect_fits(io.BytesIO(payload), request)
                    except (ArchiveError, OSError, ValueError, KeyError, IndexError) as retried:
                        raise ArchiveError(
                            "IRSA returned an invalid SPHEREx FITS product"
                        ) from retried
                else:
                    raise ArchiveError("IRSA returned an invalid SPHEREx FITS product") from exc
            if metadata["detector"] != frame["detector"]:
                raise ArchiveError("Downloaded detector differs from the discovered observation")
            metadata.update(
                {
                    "metadata_schema_version": METADATA_SCHEMA_VERSION,
                    "sha256": full_sha256(payload),
                    "bytes": len(payload),
                    "retrieved_at_utc": datetime.now(UTC).isoformat(),
                }
            )
            if not path.exists():
                self.store.write_bytes(path, payload)
            self.store.write("metadata", frame_id, metadata)
            return path, {**frame, **metadata}
