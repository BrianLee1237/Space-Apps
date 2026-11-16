"""Public local-analysis API, provenance records, and review queue."""

import hashlib
import platform
from contextlib import nullcontext
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.time import Time
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .analysis import discover_changes, matched_pairs, track_source
from .archive import ArchiveError
from .atlas import atlas_router
from .frontend import manifest_frame_entry, observation_parts
from .gaia import gaia_overlay
from .imaging import output_wcs
from .jobs import JobManager
from .models import SearchRequest
from .photometry import CHANNELS, channel_for, measure_lightcurve, wavelength_time_cells
from .processing import process_difference, process_stack, render
from .reviews import ReviewStore
from .spectrum import point_sample, resolve_pixel_sky_position
from .storage import canonical, digest

ANALYSIS_VERSION = "2.0"
SCIENCE_ROOT = Path(__file__).parent
CODE_SHA = hashlib.sha256(
    b"".join(path.name.encode() + path.read_bytes() for path in sorted(SCIENCE_ROOT.glob("*.py")))
).hexdigest()
LIBRARY_VERSIONS = {name: version(name) for name in ("astropy", "numpy", "scipy", "pillow")}
LIBRARY_VERSIONS["python"] = platform.python_version()
CALIBRATION_SHA = hashlib.sha256((SCIENCE_ROOT / "channels.json").read_bytes()).hexdigest()


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal[
        "matches",
        "photometry",
        "spectrum",
        "track",
        "stack",
        "shift-stack",
        "difference",
        "discover",
        "catalog",
    ]
    ids: list[Annotated[str, Field(pattern=r"^[a-f0-9]{24}\.[a-f0-9]{24}$")]] = Field(
        min_length=1, max_length=10000
    )
    referenceId: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}\.[a-f0-9]{24}$")
    x: float = Field(default=0.5, ge=0, le=1)
    y: float = Field(default=0.5, ge=0, le=1)
    ra: float | None = Field(default=None, ge=0, lt=360)
    dec: float | None = Field(default=None, ge=-90, le=90)
    radiusArcsec: float = Field(default=12, ge=4, le=60)
    epochDays: int = Field(default=30, ge=1, le=365)
    background: Literal["none", "constant", "plane"] = "constant"
    eastRate: float = Field(default=0, ge=-1000, le=1000)
    northRate: float = Field(default=0, ge=-1000, le=1000)
    pixels: int = Field(default=256, ge=64, le=512)
    crossmatch: bool = False

    @model_validator(mode="after")
    def position_pair(self):
        if (self.ra is None) != (self.dec is None):
            raise ValueError("Supply both ra and dec")
        self.ids = list(dict.fromkeys(self.ids))
        if self.referenceId and self.referenceId not in self.ids:
            raise ValueError("The reference observation must be in ids")
        return self


class EvidenceSubmission(BaseModel):
    record: dict

    @model_validator(mode="after")
    def bounded(self):
        if len(canonical(self.record)) > 2_000_000:
            raise ValueError("Evidence exceeds the two-megabyte record limit")
        if "note" in self.record and not isinstance(self.record["note"], str):
            raise ValueError("Evidence notes must be text")
        target = self.record.get("target")
        if target is not None:
            if not isinstance(target, dict):
                raise ValueError("Target must be an object")
            SearchRequest(
                ra=target.get("raDeg"), dec=target.get("decDeg"), fov_arcmin=target.get("fovArcmin")
            )
            if "name" in target and not isinstance(target["name"], str):
                raise ValueError("Target name must be text")
        analysis = self.record.get("analysis")
        if analysis is not None:
            if not isinstance(analysis, dict):
                raise ValueError("Analysis must be an object")
            position = analysis.get("position", {})
            if not isinstance(position, dict) or not all(
                isinstance(position.get(key), (int, float)) for key in ("raDeg", "decDeg")
            ):
                raise ValueError("Analysis needs numeric sky coordinates")
            provenance = analysis.get("provenance", {})
            if not isinstance(provenance, dict):
                raise ValueError("Analysis needs provenance")
            AnalysisRequest.model_validate(provenance.get("parameters", {}))
            if not isinstance(analysis.get("method"), str):
                raise ValueError("Analysis method must be text")
            if not isinstance(analysis.get("warnings"), list) or not all(
                isinstance(item, str) for item in analysis["warnings"]
            ):
                raise ValueError("Analysis warnings must be a list of strings")
            for field in ("samples", "channels", "cells", "measurements", "pairs"):
                if field in analysis and (
                    not isinstance(analysis[field], list)
                    or not all(isinstance(item, dict) for item in analysis[field])
                ):
                    raise ValueError(f"{field} must be a list of measurement objects")
            numeric_fields = {
                "samples": ("flux", "uncertainty", "wavelengthMicron"),
                "channels": ("channel", "count", "meanFlux"),
                "cells": ("channel", "epoch", "flux", "uncertainty", "count"),
                "measurements": ("raDeg", "decDeg", "xFraction", "yFraction", "peakSnr"),
            }
            for field, keys in numeric_fields.items():
                for item in analysis.get(field, []):
                    if not all(isinstance(item.get(key), (int, float)) for key in keys):
                        raise ValueError(f"{field} needs numeric measurement values")
                    if field in {"samples", "measurements"}:
                        if not isinstance(item.get("observedAt"), str) or not isinstance(
                            item.get("observationId"), str
                        ):
                            raise ValueError("Measurements need observation identifiers and dates")
        return self


class Assessment(BaseModel):
    reviewer: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    verdict: Literal["possible-motion", "possible-variability", "artifact", "uncertain"]
    note: str = Field(default="", max_length=2000)


def science_router(sky, gaia=None):
    router = APIRouter(prefix="/api/science", tags=["Science analysis"])
    router.include_router(atlas_router(sky.archive), prefix="/atlas")
    jobs = JobManager()
    reviews = ReviewStore(sky.store.root)

    def records_for(identifiers, progress, cancelled, reference_id=None):
        warnings, records = [], []
        selected = identifiers
        for index, identifier in enumerate(selected):
            cancelled()
            search_id, frame_id, entry = manifest_frame_entry(sky, identifier)
            try:
                path, metadata = sky.frame(search_id, frame_id)
            except ArchiveError as exc:
                warnings.append(f"Skipped {identifier}: {exc}")
                continue
            records.append(
                {
                    "id": identifier,
                    "path": path,
                    "request": SearchRequest.model_validate(sky.manifest(search_id)["query"]),
                    "metadata": metadata,
                    "observedAt": entry["observed_at_utc"],
                    "detector": entry["detector"],
                    "wavelengthMicron": metadata.get("central_wavelength_um"),
                    "flags": metadata.get("center_flag_names", []),
                }
            )
            progress(index + 1, len(selected), "Inspecting actual exposure metadata")
        # Avoid treating reprocessed releases of a single physical exposure as independent.
        unique = {}
        for record in sorted(
            records,
            key=lambda row: (
                row["id"] == reference_id,
                "dr1" in row["metadata"].get("collection", ""),
            ),
        ):
            meta = record["metadata"]
            key = (
                meta.get("obs_id") or record["id"].split(".")[-1],
                record["detector"],
                record["observedAt"],
            )
            unique[key] = record
        if len(unique) < len(records):
            warnings.append(
                f"Deduplicated {len(records) - len(unique)} reprocessed physical exposures."
            )
        return sorted(unique.values(), key=lambda row: row["observedAt"]), warnings

    def bounded_identifiers(identifiers):
        if len(identifiers) <= 256:
            return identifiers, []
        groups = {}
        indexes = {}
        for identifier in identifiers:
            search_id, frame_id = observation_parts(identifier)
            if search_id not in indexes:
                indexes[search_id] = {
                    row["frame_id"]: row for row in sky.manifest(search_id)["frames"]
                }
            entry = indexes[search_id][frame_id]
            groups.setdefault(entry["detector"], []).append(identifier)
        selected = []
        for index, values in enumerate(groups.values()):
            count = min(len(values), 256 // len(groups) + (index < 256 % len(groups)))
            selected.extend(
                values[round(i * (len(values) - 1) / max(1, count - 1))] for i in range(count)
            )
        selected_set = set(selected)
        remaining = [identifier for identifier in identifiers if identifier not in selected_set]
        needed = min(256 - len(selected), len(remaining))
        selected.extend(
            remaining[round(i * (len(remaining) - 1) / max(1, needed - 1))] for i in range(needed)
        )
        return selected, [
            f"Inspected {len(selected)} of {len(identifiers)} exposures, "
            "balanced across detectors and time."
        ]

    def position_for(parameters):
        identifier = parameters.referenceId or parameters.ids[0]
        search_id, _ = observation_parts(identifier)
        request = SearchRequest.model_validate(sky.manifest(search_id)["query"])
        if parameters.ra is not None:
            return parameters.ra, parameters.dec, request
        ra, dec = resolve_pixel_sky_position(request, 512, parameters.x, parameters.y)
        return ra, dec, request

    def save_image(image):
        key = digest(image)
        sky.store.write_bytes(sky.store.path("previews", key, ".png"), image)
        return f"/api/science/previews/{key}.png"

    def execute(parameters, progress, cancelled):
        ra, dec, request = position_for(parameters)
        identifiers = (
            [parameters.referenceId or parameters.ids[0]]
            if parameters.kind == "catalog"
            else parameters.ids
        )
        warnings = []
        if parameters.kind == "spectrum":
            query = SearchRequest(ra=ra, dec=dec, fov_arcmin=min(6, request.fov_arcmin))
            manifest = sky.search(query)
            identifiers = [
                f"{manifest['search_id']}.{row['frame_id']}" for row in manifest["frames"]
            ]
            if not manifest["complete"]:
                warnings.append(
                    "The all-detector archive search is truncated; spectral coverage is partial."
                )
        identifiers, bounded_warnings = bounded_identifiers(identifiers)
        if (
            parameters.kind != "spectrum"
            and parameters.referenceId in parameters.ids
            and parameters.referenceId not in identifiers
        ):
            identifiers[-1] = parameters.referenceId
        warnings.extend(bounded_warnings)
        pin = sky.store.pin(identifiers) if hasattr(sky.store, "pin") else nullcontext()
        with pin:
            records, notes = records_for(identifiers, progress, cancelled, parameters.referenceId)
            warnings.extend(notes)
            if not records:
                raise ValueError("No usable archive exposures were retrieved")
            if parameters.referenceId and parameters.kind != "spectrum":
                if not any(row["id"] == parameters.referenceId for row in records):
                    raise ValueError("The selected reference observation could not be retrieved")
            reference = next(
                (row for row in records if row["id"] == parameters.referenceId), records[0]
            )
            if parameters.kind in {"photometry", "spectrum"}:
                result = measure_lightcurve(
                    records, ra, dec, parameters.radiusArcsec, progress, cancelled
                )
                result["detectorCoverage"] = sorted(
                    {point["detector"] for point in result["samples"]}
                )
                if parameters.kind == "spectrum" and len(result["detectorCoverage"]) < 6:
                    result["warnings"].append(
                        "Measured detector coverage: "
                        + str(result["detectorCoverage"])
                        + ". Missing detectors have no valid returned measurements."
                    )
                result["cells"] = wavelength_time_cells(result["samples"], parameters.epochDays)
            elif parameters.kind == "catalog":
                if gaia is None:
                    raise ValueError("Gaia catalog access is unavailable")
                query = SearchRequest(ra=ra, dec=dec, fov_arcmin=1)
                sources, catalog_warnings = gaia_overlay(gaia, query, reference["observedAt"])
                center = SkyCoord(ra, dec, unit="deg")
                counterparts = [
                    {
                        **row,
                        "separationArcsec": float(
                            center.separation(
                                SkyCoord(row["raDeg"], row["decDeg"], unit="deg")
                            ).arcsec
                        ),
                    }
                    for row in sources
                ]
                counterparts.sort(key=lambda row: row["separationArcsec"])
                result = {
                    "counterparts": counterparts[:10],
                    "catalog": "Gaia DR3",
                    "method": "Nearby Gaia DR3 catalog positions propagated to the reference epoch",
                    "warnings": [
                        *catalog_warnings,
                        "Nearby catalog entries require source-association checks. "
                        "Missing optical counterparts do not establish a new object.",
                    ],
                }
            elif parameters.kind == "discover":
                result = discover_changes(records, progress, cancelled)
                if parameters.crossmatch and gaia is not None:
                    for candidate in result["candidates"]:
                        cancelled()
                        try:
                            sources, catalog_warnings = gaia_overlay(
                                gaia, request, candidate["laterAt"]
                            )
                        except ArchiveError as exc:
                            result["warnings"].append(str(exc))
                            break
                        position = SkyCoord(candidate["raDeg"], candidate["decDeg"], unit="deg")
                        matches = []
                        for row in sources:
                            separation = float(
                                position.separation(
                                    SkyCoord(row["raDeg"], row["decDeg"], unit="deg")
                                ).arcsec
                            )
                            if separation <= candidate["evidence"][0]["associationRadiusArcsec"]:
                                matches.append({**row, "separationArcsec": separation})
                        candidate["catalogMatches"] = sorted(
                            matches, key=lambda row: row["separationArcsec"]
                        )
                    result["warnings"].append(
                        "Gaia cross-matches use optical catalog positions and "
                        "an incomplete brightness-limited field sample."
                    )
            elif parameters.kind == "matches":
                # At a selected source, spectral compatibility uses that source's pixel.
                for row in records:
                    sample = point_sample(row["path"], ra, dec)
                    row["wavelengthMicron"] = sample["wavelengthMicron"] if sample else None
                result = {
                    "pairs": matched_pairs(records, limit=100),
                    "inspected": len(records),
                    "observations": [
                        {
                            "id": row["id"],
                            "centralWavelengthMicron": row["wavelengthMicron"],
                            "flags": row["flags"],
                        }
                        for row in records
                    ],
                    "method": "Full-search native-pixel wavelength and same-field matching",
                }
            elif parameters.kind == "track":
                x, y = output_wcs(reference["request"], 512).world_to_pixel(
                    SkyCoord(ra, dec, unit="deg")
                )
                result = track_source(
                    records,
                    reference["id"],
                    float(x) / 511,
                    1 - float(y) / 511,
                    progress=progress,
                    cancelled=cancelled,
                )
            else:
                sample = point_sample(reference["path"], ra, dec)
                if sample is None:
                    raise ValueError(
                        "The reference source pixel is invalid or outside this exposure"
                    )
                channel = channel_for(sample["wavelengthMicron"], reference["detector"])
                compatible = []
                for row in records:
                    cancelled()
                    other = point_sample(row["path"], ra, dec)
                    same_field = all(
                        abs(getattr(row["request"], key) - getattr(request, key)) < 1e-7
                        for key in ("ra", "dec", "fov_arcmin")
                    )
                    if other and same_field and row["detector"] == reference["detector"]:
                        if (
                            channel is not None
                            and channel_for(other["wavelengthMicron"], row["detector"]) == channel
                        ):
                            compatible.append(row)
                if len(compatible) < 2:
                    raise ValueError(
                        "This source needs two valid exposures in the same calibrated channel"
                    )
                if len(compatible) > 64:
                    compatible = [
                        compatible[round(i * (len(compatible) - 1) / 63)] for i in range(64)
                    ]
                    warnings.append(
                        "Image processing uses 64 exposures spread across the available epochs."
                    )
                bounds = (CHANNELS[channel - 1]["WL_MIN"], CHANNELS[channel - 1]["WL_MAX"])
                if parameters.kind == "difference":
                    a, b = compatible[0], compatible[-1]
                    image, significance, result = process_difference(
                        a,
                        b,
                        request,
                        parameters.pixels,
                        parameters.background,
                        target_pixel=output_wcs(request, parameters.pixels).world_to_pixel(
                            SkyCoord(ra, dec, unit="deg")
                        ),
                        channel_bounds=bounds,
                    )
                    result.update(
                        {
                            "earlierAt": a["observedAt"],
                            "laterAt": b["observedAt"],
                            "inputObservationIds": [a["id"], b["id"]],
                            "significanceUrl": save_image(render(significance, True)),
                        }
                    )
                else:
                    rates = (
                        (parameters.eastRate, parameters.northRate)
                        if parameters.kind == "shift-stack"
                        else None
                    )
                    image, variance, result = process_stack(
                        compatible,
                        request,
                        parameters.pixels,
                        parameters.background,
                        rates,
                        Time(reference["observedAt"]).mjd,
                        progress,
                        cancelled,
                        channel_bounds=bounds,
                    )
                    snr = np.divide(
                        image,
                        np.sqrt(variance),
                        out=np.full_like(image, np.nan),
                        where=variance > 0,
                    )
                    result["significanceUrl"] = save_image(render(snr, True))
                    result["inputObservationIds"] = [row["id"] for row in compatible]
                    if rates:
                        static, _, _ = process_stack(
                            compatible,
                            request,
                            parameters.pixels,
                            parameters.background,
                            progress=progress,
                            cancelled=cancelled,
                            channel_bounds=bounds,
                        )
                        result["staticImageUrl"] = save_image(render(static))
                        result["eastRate"], result["northRate"] = rates
                result["imageUrl"] = save_image(render(image, parameters.kind == "difference"))
                result["channel"] = channel
                result["method"] = (
                    "Common-grid variance propagation, calibrated-channel selection, "
                    "robust sky model"
                )
                warnings.extend(
                    [
                        "Stacked epochs can average intrinsic variability and blur moving sources.",
                        "Resampling correlations, absolute calibration, and background-model "
                        "systematics remain additional uncertainties.",
                    ]
                )
            cancelled()
            result["warnings"] = [*warnings, *result.get("warnings", [])]
            result["position"] = {"raDeg": ra, "decDeg": dec}
            result["provenance"] = {
                "algorithmVersion": ANALYSIS_VERSION,
                "libraries": LIBRARY_VERSIONS,
                "codeSha256": CODE_SHA,
                "calibrationSha256": CALIBRATION_SHA,
                "parameters": parameters.model_dump(),
                "observations": [
                    {
                        "id": row["id"],
                        "observedAt": row["observedAt"],
                        "sha256": row["metadata"].get("sha256"),
                        "release": row["metadata"].get("collection"),
                        "processingVersion": row["metadata"].get("processing_version"),
                    }
                    for row in records
                ],
            }
            return result

    @router.post("/jobs")
    def submit(parameters: AnalysisRequest):
        def reusable(result):
            for name in ("imageUrl", "significanceUrl", "staticImageUrl"):
                if result.get(name):
                    key = result[name].rsplit("/", 1)[-1].removesuffix(".png")
                    if not sky.store.path("previews", key, ".png").is_file():
                        return False
            return True

        snapshot, token = jobs.submit(
            parameters.kind,
            parameters.model_dump(),
            lambda progress, cancelled: execute(parameters, progress, cancelled),
            reusable,
        )
        return {**snapshot, "subscription": token}

    @router.get("/jobs/{job_id}")
    def inspect_job(job_id: str):
        return jobs.snapshot(job_id)

    @router.delete("/jobs/{job_id}/{subscription}")
    def release_job(job_id: str, subscription: str):
        return jobs.release(job_id, subscription)

    @router.get("/previews/{key}.png")
    def preview(key: str):
        path = sky.store.path("previews", key, ".png")
        if not path.is_file():
            raise HTTPException(
                404, "Preview expired from the temporary cache. Rerun the saved analysis."
            )
        return FileResponse(path, media_type="image/png")

    @router.get("/channels")
    def channels():
        return {
            "channels": [{"index": i + 1, **row} for i, row in enumerate(CHANNELS)],
            "calibrationSha256": CALIBRATION_SHA,
        }

    @router.get("/cache")
    def cache():
        return sky.store.statistics()

    @router.get("/evidence")
    def evidence():
        return {
            "entries": reviews.list(),
            "reviewers": "Local browser identities; independently unverified",
        }

    @router.post("/evidence")
    def save_evidence(submission: EvidenceSubmission):
        return {"id": reviews.submit(submission.record)}

    @router.get("/evidence/{key}")
    def get_evidence(key: str):
        return reviews.get(key)

    @router.post("/evidence/{key}/assessments")
    def assess(key: str, assessment: Assessment):
        reviews.assess(key, assessment.reviewer, assessment.verdict, assessment.note)
        return {"saved": True}

    return router, jobs
