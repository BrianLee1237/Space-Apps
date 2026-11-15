"""Compatibility routes for the existing, unchanged React frontend."""

import re
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from .archive import ArchiveError
from .candidates import detect_candidates
from .gaia import gaia_overlay
from .imaging import combine_png, difference_png, preview_png
from .models import SearchRequest
from .spectral import CHANNELS_PER_DETECTOR, wavelength_sorted_groups
from .spectrum import build_fingerprint, resolve_pixel_sky_position
from .targets import TARGETS


def observation_parts(identifier):
    if not re.fullmatch(r"[a-f0-9]{24}\.[a-f0-9]{24}", identifier):
        raise KeyError(identifier)
    return identifier.split(".")


def manifest_frame_entry(sky, identifier):
    """Resolve an observation id to its manifest-listed frame entry (mjd_start,
    observed_at_utc, ...) without downloading that frame's FITS cutout."""
    search_id, frame_id = observation_parts(identifier)
    manifest = sky.manifest(search_id)
    entry = next((f for f in manifest["frames"] if f["frame_id"] == frame_id), None)
    if entry is None:
        raise KeyError(identifier)
    return search_id, frame_id, entry


def resolve_difference_pair(sky, from_id, to_id):
    """Resolve fromId/toId to (request, earlier_path, later_path, warnings).

    The pair is reordered into true chronological order by each frame's own
    observation time, so the 'earlier'/'later' roles -- and the "red means
    brighter in the later epoch" convention documented alongside this feature
    -- hold regardless of which id the caller happened to label fromId vs
    toId. The alignment grid is always the chronologically earlier frame's
    own search, with a warning when the two searches aren't comparable.
    """
    a_search, a_frame = observation_parts(from_id)
    b_search, b_frame = observation_parts(to_id)
    a_path, a_metadata = sky.frame(a_search, a_frame)
    b_path, b_metadata = sky.frame(b_search, b_frame)
    swapped = b_metadata["mjd_start"] < a_metadata["mjd_start"]
    if swapped:
        a_search, a_path, a_metadata, b_search, b_path, b_metadata = (
            b_search,
            b_path,
            b_metadata,
            a_search,
            a_path,
            a_metadata,
        )
    warnings = []
    if swapped:
        warnings.append(
            "The requested 'later' observation predates the requested 'earlier' one; "
            "the two were swapped so red consistently means brighter in the later epoch."
        )
    if a_metadata["detector"] != b_metadata["detector"]:
        warnings.append(
            "The two frames use different detectors with different bandpasses; "
            "the subtraction mixes wavelength coverage."
        )
    earlier_query = sky.manifest(a_search)["query"]
    later_query = sky.manifest(b_search)["query"]
    if (
        earlier_query["ra"] != later_query["ra"]
        or earlier_query["dec"] != later_query["dec"]
        or earlier_query["fov_arcmin"] != later_query["fov_arcmin"]
    ):
        warnings.append(
            "The two observations come from searches with a different field center or "
            "field of view; the later cutout is reprojected onto the earlier search's "
            "grid and the comparison may not be spatially meaningful."
        )
    request = SearchRequest.model_validate(earlier_query)
    return request, a_path, b_path, warnings


def frontend_router(sky, gaia):
    router = APIRouter(prefix="/api", tags=["Frontend"])

    @router.get("/resolve")
    def resolve(name: Annotated[str, Query(min_length=1, max_length=128)]):
        normalized = name.strip().casefold().replace("’", "'")
        aliases = {"eps ind b": "epsilon indi b", "rw aur": "rw aurigae", "r dra": "r draconis"}
        normalized = aliases.get(normalized, normalized)
        for target in TARGETS:
            if normalized in {target["name"].casefold(), target["id"]}:
                return {
                    "raDeg": target["ra"],
                    "decDeg": target["dec"],
                    "name": target["name"],
                    "coordinateSource": target["coordinate_source"],
                }
        raise HTTPException(422, "Choose one of the five guided targets or enter sky coordinates.")

    def build_observation(search_id, frame, limits):
        identifier = search_id + "." + frame["frame_id"]
        image_params = urlencode({"pixels": 512, **limits})
        observation = {
            "id": identifier,
            "observedAt": frame["observed_at_utc"],
            "imageUrl": f"/api/images/{identifier}.png?{image_params}",
            "release": frame["collection"].removeprefix("spherex_").upper(),
            "detector": frame["detector"],
            "imageAligned": True,
            "width": 512,
            "height": 512,
            "fitsUrl": frame["links"]["fits"],
            "metadataUrl": frame["links"]["metadata"],
        }
        exposure = frame["archive_metadata"].get("t_exptime")
        if exposure is not None:
            observation["exposureSeconds"] = exposure
        # Missing flags are omitted until a frame's actual FITS has been inspected.
        try:
            metadata = sky.store.read("metadata", frame["frame_id"])
            observation["flags"] = metadata["center_flag_names"]
            observation["centralWavelengthMicron"] = metadata["central_wavelength_um"]
        except KeyError:
            pass
        return observation

    def display_limits(search_id, frame):
        _, metadata = sky.frame(search_id, frame["frame_id"])
        percentiles = metadata.get("science_percentiles_1_50_99")
        if not percentiles:
            return {}
        low, _, high = percentiles
        return {"vmin": low, "vmax": high if high > low else low + 1}

    @router.get("/observations")
    def observations(
        ra: Annotated[float, Query(ge=0, lt=360, allow_inf_nan=False)],
        dec: Annotated[float, Query(ge=-90, le=90, allow_inf_nan=False)],
        fov: Annotated[float, Query(ge=0.5, le=60, allow_inf_nan=False)] = 10,
        mode: Literal["auto", "detector", "channel"] = "auto",
        index: Annotated[int | None, Query(ge=1, le=102)] = None,
    ):
        if mode == "detector" and (index is None or index > 6):
            raise HTTPException(422, "Detector mode requires index between 1 and 6.")
        if mode == "channel" and index is None:
            raise HTTPException(422, "Channel mode requires index between 1 and 102.")
        channel_warnings = []
        if mode == "channel":
            detector = (index - 1) // CHANNELS_PER_DETECTOR + 1
            channel_slot = (index - 1) % CHANNELS_PER_DETECTOR
        else:
            # A single detector keeps the initial animation within one detector bandpass.
            detector = index if mode == "detector" else 6
        query = SearchRequest(ra=ra, dec=dec, fov_arcmin=fov, detectors=(detector,))
        manifest = sky.search(query)
        if not manifest["complete"]:
            raise HTTPException(
                422, "The archive truncated this search. Use /v1/search with a narrower time range."
            )
        frames = manifest["frames"]
        search_id = manifest["search_id"]

        if mode == "channel" and frames:
            # SPHEREx's linear variable filter means the detector's recorded
            # bandpass for a given exposure varies with dither position.
            # "Channel N" is real data closest to the Nth of those recorded
            # bandpasses, not a fixed SPHEREx-defined bin -- see
            # spectral.wavelength_sorted_groups.
            chunks, wave_min, wave_max = wavelength_sorted_groups(frames)
            frames = chunks[channel_slot]
            if wave_min is None:
                channel_warnings.append(
                    f"No detector {detector} exposure in this search reported a usable "
                    "bandpass, so a wavelength could not be measured to form channels."
                )
            elif frames:
                channel_warnings.append(
                    f"Channel {index} groups detector {detector}'s {len(frames)} real "
                    "exposure(s) whose own recorded bandpass (range observed for this "
                    f"search: {wave_min:.3f}-{wave_max:.3f} micron) falls in roughly the "
                    f"{channel_slot + 1} of {CHANNELS_PER_DETECTOR} wavelength-sorted "
                    "groups for this detector -- an empirical grouping, not SPHEREx's own "
                    "fixed channel table."
                )
            else:
                channel_warnings.append(
                    f"Detector {detector} has fewer real exposures than the "
                    f"{CHANNELS_PER_DETECTOR} wavelength-sorted channel groups; this "
                    "particular channel slot has none."
                )

        limits = display_limits(search_id, frames[0]) if frames else {}
        result = [build_observation(search_id, frame, limits) for frame in frames]
        return {
            "target": {"raDeg": ra, "decDeg": dec, "fovArcmin": fov},
            "observations": result,
            "dataUpdatedAt": manifest["created_at_utc"],
            "dataRelease": ", ".join(sorted({o["release"] for o in result})),
            "searchId": search_id,
            "selectedDetector": detector,
            "warnings": [*manifest["warnings"], *channel_warnings],
        }

    @router.get("/images/{identifier}.png")
    def image(
        identifier: str,
        pixels: Annotated[int, Query(ge=32, le=1024)] = 512,
        vmin: Annotated[float | None, Query(allow_inf_nan=False)] = None,
        vmax: Annotated[float | None, Query(allow_inf_nan=False)] = None,
    ):
        if (vmin is None) != (vmax is None) or (vmin is not None and vmin >= vmax):
            raise HTTPException(422, "Supply both vmin and vmax with vmin < vmax.")
        search_id, frame_id = observation_parts(identifier)
        path, _ = sky.frame(search_id, frame_id)
        query = SearchRequest.model_validate(sky.manifest(search_id)["query"])
        png, headers = preview_png(path, query, pixels, vmin, vmax)
        return Response(png, media_type="image/png", headers=headers)

    @router.get("/difference")
    def difference(
        fromId: Annotated[str, Query(min_length=1)],
        toId: Annotated[str, Query(min_length=1)],
        pixels: Annotated[int, Query(ge=32, le=1024)] = 512,
        reject_bits: Annotated[int, Query(ge=0, le=2**32 - 1)] = 0,
        subtract_zodi: bool = False,
    ):
        _, _, _, pair_warnings = resolve_difference_pair(sky, fromId, toId)
        warnings = [
            "Not a flux-calibrated difference image: no PSF matching or background fitting.",
            "Residuals near bright, saturated, or flagged pixels are not scientifically validated.",
            *pair_warnings,
        ]
        image_params = urlencode(
            {
                "fromId": fromId,
                "toId": toId,
                "pixels": pixels,
                "reject_bits": reject_bits,
                "subtract_zodi": subtract_zodi,
            }
        )
        return {
            "imageUrl": f"/api/difference.png?{image_params}",
            "method": (
                "Both cutouts resampled with bilinear interpolation onto one shared "
                "ICRS tangent-plane grid (the earlier frame's requested field center "
                "and pixel scale), then to-minus-from subtraction with a zero-centered "
                "asinh stretch: red where the later frame is brighter, blue where it is dimmer."
            ),
            "warnings": warnings,
        }

    @router.get("/difference.png")
    def difference_image_route(
        fromId: Annotated[str, Query(min_length=1)],
        toId: Annotated[str, Query(min_length=1)],
        pixels: Annotated[int, Query(ge=32, le=1024)] = 512,
        reject_bits: Annotated[int, Query(ge=0, le=2**32 - 1)] = 0,
        subtract_zodi: bool = False,
    ):
        request, path_earlier, path_later, pair_warnings = resolve_difference_pair(
            sky, fromId, toId
        )
        png, headers = difference_png(
            path_earlier, path_later, request, pixels, reject_bits, subtract_zodi
        )
        if pair_warnings:
            headers = {**headers, "X-Difference-Warning": " | ".join(pair_warnings)}
        return Response(png, media_type="image/png", headers=headers)

    def resolve_combine_ids(ids):
        identifiers = [value for value in ids.split(",") if value]
        if len(identifiers) < 2:
            raise HTTPException(422, "Provide at least two comma-separated observation ids.")
        parsed = [observation_parts(identifier) for identifier in identifiers]
        detectors = {
            sky.frame(search_id, frame_id)[1]["detector"] for search_id, frame_id in parsed
        }
        warnings = [
            "This is a simple pixel-mean coadd: no PSF matching, cosmic-ray "
            "rejection, or outlier clipping beyond the rejected quality-flag bits.",
        ]
        if len(detectors) > 1:
            warnings.append(
                "The combined exposures use different detectors with different "
                "bandpasses; averaging mixes wavelength coverage."
            )
        request = SearchRequest.model_validate(sky.manifest(parsed[0][0])["query"])
        return identifiers, parsed, request, warnings

    @router.get("/combine")
    def combine(
        ids: Annotated[str, Query(min_length=1)],
        pixels: Annotated[int, Query(ge=32, le=1024)] = 512,
        reject_bits: Annotated[int, Query(ge=0, le=2**32 - 1)] = 0,
        subtract_zodi: bool = False,
    ):
        identifiers, _, _, warnings = resolve_combine_ids(ids)
        image_params = urlencode(
            {
                "ids": ids,
                "pixels": pixels,
                "reject_bits": reject_bits,
                "subtract_zodi": subtract_zodi,
            }
        )
        return {
            "imageUrl": f"/api/combine.png?{image_params}",
            "frameCount": len(identifiers),
            "method": (
                f"Mean-combine of {len(identifiers)} real exposures resampled onto one "
                "shared ICRS tangent-plane grid (the first observation's own search), "
                "keeping only pixels covered by at least half of them -- reduces "
                "per-pixel noise by roughly the square root of the exposure count."
            ),
            "warnings": warnings,
        }

    @router.get("/combine.png")
    def combine_image_route(
        ids: Annotated[str, Query(min_length=1)],
        pixels: Annotated[int, Query(ge=32, le=1024)] = 512,
        reject_bits: Annotated[int, Query(ge=0, le=2**32 - 1)] = 0,
        subtract_zodi: bool = False,
    ):
        _, parsed, request, _ = resolve_combine_ids(ids)
        paths = [sky.frame(search_id, frame_id)[0] for search_id, frame_id in parsed]
        png, headers = combine_png(paths, request, pixels, None, None, reject_bits, subtract_zodi)
        return Response(png, media_type="image/png", headers=headers)

    @router.get("/overlays")
    def overlays(
        observationId: Annotated[str, Query(min_length=1)],
        catalog: Literal["gaia-dr3"] = "gaia-dr3",
    ):
        search_id, frame_id = observation_parts(observationId)
        _, metadata = sky.frame(search_id, frame_id)
        request = SearchRequest.model_validate(sky.manifest(search_id)["query"])
        try:
            sources, warnings = gaia_overlay(gaia, request, metadata["observed_at_utc"])
        except ArchiveError as exc:
            raise HTTPException(502, str(exc)) from exc
        return {"sources": sources, "catalog": catalog, "warnings": warnings}

    @router.get("/candidates")
    def candidates(
        ra: Annotated[float, Query(ge=0, lt=360, allow_inf_nan=False)],
        dec: Annotated[float, Query(ge=-90, le=90, allow_inf_nan=False)],
        fov: Annotated[float, Query(ge=0.5, le=60, allow_inf_nan=False)],
        ids: Annotated[str, Query(min_length=1)],
    ):
        identifiers = [value for value in ids.split(",") if value]
        if len(identifiers) < 2:
            raise HTTPException(422, "Provide at least two comma-separated observation ids.")
        entries = [manifest_frame_entry(sky, identifier) for identifier in identifiers]
        entries.sort(key=lambda entry: entry[2]["mjd_start"])
        earlier_search, earlier_frame, earlier_entry = entries[0]
        later_search, later_frame, later_entry = entries[-1]
        path_earlier, _ = sky.frame(earlier_search, earlier_frame)
        path_later, _ = sky.frame(later_search, later_frame)
        request = SearchRequest.model_validate(sky.manifest(earlier_search)["query"])
        found, warnings = detect_candidates(
            path_earlier,
            path_later,
            request,
            earlier_entry["observed_at_utc"],
            later_entry["observed_at_utc"],
        )
        if (
            abs(request.ra - ra) > 1e-6
            or abs(request.dec - dec) > 1e-6
            or abs(request.fov_arcmin - fov) > 1e-6
        ):
            warnings.append(
                "The requested ra/dec/fov differ from the earliest observation's own "
                "search; candidates are positioned on that observation's grid."
            )
        return {
            "candidates": found,
            "method": found[0]["method"] if found else "blob detection on a difference image",
            "notes": (
                f"Compared {len(identifiers)} requested observations by using the earliest "
                "and latest by observation time, for maximum baseline."
            ),
            "warnings": warnings,
        }

    @router.get("/spectrum")
    def spectrum(
        observationId: Annotated[str | None, Query(min_length=1)] = None,
        x: Annotated[float | None, Query(ge=0, le=1)] = None,
        y: Annotated[float | None, Query(ge=0, le=1)] = None,
        ra: Annotated[float | None, Query(ge=0, lt=360, allow_inf_nan=False)] = None,
        dec: Annotated[float | None, Query(ge=-90, le=90, allow_inf_nan=False)] = None,
    ):
        if ra is not None and dec is not None:
            target_ra, target_dec = ra, dec
            fov_arcmin = 2.0
            label = f"RA {ra:.5f}°, Dec {dec:.5f}°"
        elif observationId is not None and x is not None and y is not None:
            search_id, _ = observation_parts(observationId)
            request = SearchRequest.model_validate(sky.manifest(search_id)["query"])
            target_ra, target_dec = resolve_pixel_sky_position(request, 512, x, y)
            fov_arcmin = request.fov_arcmin
            label = f"Pixel ({x:.2f}, {y:.2f}) of observation {observationId}"
        else:
            raise HTTPException(422, "Provide ra and dec, or observationId with x and y.")

        samples, fingerprint_warnings = build_fingerprint(sky, target_ra, target_dec, fov_arcmin)
        return {
            "samples": [
                {
                    "wavelengthMicron": sample["wavelengthMicron"],
                    "flux": sample["flux"],
                    "uncertainty": sample["uncertainty"],
                    "qualityFlags": sample["qualityFlags"],
                }
                for sample in samples
            ],
            "fluxUnit": samples[0]["bunit"] if samples else "MJy/sr",
            "extractionMethod": (
                "Single-pixel real flux read directly from one native FITS cutout per "
                "available empirical wavelength channel (nearest-pixel, no PSF "
                "photometry or aperture correction), at the exact requested sky position."
            ),
            "sourceLabel": label,
            "warnings": [
                *fingerprint_warnings,
                "This is a single-pixel sample, not PSF-fit or aperture photometry; "
                "nearby bright or flagged pixels are not corrected for.",
            ],
        }

    return router


def frontend_dist():
    return Path(__file__).resolve().parents[3] / "frontend" / "dist"
