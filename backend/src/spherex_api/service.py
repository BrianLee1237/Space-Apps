import io
import time
from datetime import UTC, datetime

from filelock import FileLock

from .archive import ArchiveClient, ArchiveError
from .config import Settings
from .imaging import full_sha256, inspect_fits
from .models import SearchRequest
from .storage import Store, canonical, digest

METADATA_SCHEMA_VERSION = 1


class SkyService:
    def __init__(self, settings: Settings, archive=None):
        self.settings = settings
        self.store = Store(settings)
        self.archive = archive or ArchiveClient(settings)

    def search(self, request: SearchRequest, refresh=False):
        key = digest(canonical(request.model_dump(mode="json")))
        lock = self.store.path("queries", key, ".lock")
        with FileLock(str(lock), timeout=180):
            if not refresh:
                cached = self.store.cached_search(key)
                if cached:
                    return {**cached, "cache_hit": True}
            frames, overflow, upstream_count, params = self.archive.search(request)
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
            now = datetime.now(UTC).isoformat()
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
            self.store.write("queries", key, {"search_id": search_id, "created_unix": time.time()})
            return {**manifest, "cache_hit": False}

    def manifest(self, search_id):
        return self.store.read("searches", search_id)

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
                        return path, {**frame, **metadata}
                except KeyError:
                    pass
            request = SearchRequest.model_validate(manifest["query"])
            if path.exists():
                payload = path.read_bytes()
            else:
                payload = self.archive.fetch(frame["cutout_url"])
            metadata = inspect_fits(io.BytesIO(payload), request)
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
