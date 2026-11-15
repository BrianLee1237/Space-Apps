"""Compatibility routes for the existing, unchanged React frontend."""

import json
import re
from concurrent.futures import ThreadPoolExecutor
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
from .spectrum import build_fingerprint, resolve_pixel_sky_position
from .targets import TARGETS

CHANNELS = json.loads(Path(__file__).with_name("channels.json").read_text())


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

    @router.get("/metadata")
    def metadata(observationId: str):
        search_id, frame_id = observation_parts(observationId)
        _, values = sky.frame(search_id, frame_id)
        return {
            "id": observationId,
            "flags": values.get("center_flag_names", []),
            "centralWavelengthMicron": values.get("central_wavelength_um"),
            "bandwidthMicron": values.get("central_bandwidth_um"),
            "psfFwhmArcsec": values.get("psf_fwhm_arcsec"),
        }

    @router.get("/observations")
    def observations(
        ra: Annotated[float, Query(ge=0, lt=360, allow_inf_nan=False)],
        dec: Annotated[float, Query(ge=-90, le=90, allow_inf_nan=False)],
        fov: Annotated[float, Query(ge=0.5, le=60, allow_inf_nan=False)] = 10,
        mode: Literal["auto", "detector", "channel"] = "auto",
        index: Annotated[int | None, Query(ge=1, le=102)] = None,
    ):
        if mode == "channel" and index is None:
            raise HTTPException(422, "Choose a channel between 1 and 102.")
        if mode == "detector" and (index is None or index > 6):
            raise HTTPException(422, "Detector mode requires index between 1 and 6.")
        # A single detector keeps the initial animation within one detector bandpass.
        channel = CHANNELS[index - 1] if mode == "channel" else None
        detector = channel["detector"] if channel else index if mode == "detector" else 6
        query = SearchRequest(ra=ra, dec=dec, fov_arcmin=fov, detectors=(detector,))
        manifest = sky.search(query)
        if not manifest["complete"]:
            raise HTTPException(
                422, "The archive truncated this search. Use /v1/search with a narrower time range."
            )
        frames = manifest["frames"]
        if channel:

            def matches(frame):
                try:
                    _, metadata = sky.frame(manifest["search_id"], frame["frame_id"])
                    wavelength = metadata.get("central_wavelength_um")
                    return (
                        wavelength is not None
                        and channel["WL_MIN"] <= wavelength <= channel["WL_MAX"]
                    )
                except ArchiveError:
                    return None

            with ThreadPoolExecutor(max_workers=2) as pool:
                matches_by_frame = list(pool.map(matches, frames))
                failed_count = matches_by_frame.count(None)
                if frames and failed_count == len(frames):
                    raise ArchiveError("Channel cutouts failed retrieval. Retry the search.")
                frames = [
                    frame for frame, match in zip(frames, matches_by_frame, strict=True) if match
                ]
            manifest = {
                **manifest,
                "warnings": [
                    *manifest["warnings"],
                    f"Channel {index} window "
                    f"{channel['WL_MIN']:.4f}–{channel['WL_MAX']:.4f} µm. "
                    "Pixels outside that approximate spectral-WCS window are transparent.",
                ],
            }
            if failed_count:
                manifest["warnings"].append(
                    f"{failed_count} cutouts failed retrieval. This channel sequence is partial."
                )
        limits = {}
        if frames:
            _, first_metadata = sky.frame(manifest["search_id"], frames[0]["frame_id"])
            percentiles = first_metadata.get("science_percentiles_1_50_99")
            if percentiles:
                low, _, high = percentiles
                limits = {"vmin": low, "vmax": high if high > low else low + 1}
        result = []
        for frame in frames:
            identifier = manifest["search_id"] + "." + frame["frame_id"]
            image_params = urlencode(
                {"pixels": 512, **limits, **({"channel": index} if channel else {})}
            )
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
            if channel:
                observation["channel"] = index
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
            result.append(observation)
        return {
            "target": {"raDeg": ra, "decDeg": dec, "fovArcmin": fov},
            "observations": result,
            "dataUpdatedAt": manifest["created_at_utc"],
            "dataRelease": ", ".join(sorted({o["release"] for o in result})),
            "searchId": manifest["search_id"],
            "selectedDetector": detector,
            "warnings": manifest["warnings"],
        }

    @router.get("/images/{identifier}.png")
    def image(
        identifier: str,
        pixels: Annotated[int, Query(ge=32, le=1024)] = 512,
        vmin: Annotated[float | None, Query(allow_inf_nan=False)] = None,
        vmax: Annotated[float | None, Query(allow_inf_nan=False)] = None,
        channel: Annotated[int | None, Query(ge=1, le=102)] = None,
    ):
        if (vmin is None) != (vmax is None) or (vmin is not None and vmin >= vmax):
            raise HTTPException(422, "Supply both vmin and vmax with vmin < vmax.")
        search_id, frame_id = observation_parts(identifier)
        path, _ = sky.frame(search_id, frame_id)
        query = SearchRequest.model_validate(sky.manifest(search_id)["query"])
        bounds = (
            (CHANNELS[channel - 1]["WL_MIN"], CHANNELS[channel - 1]["WL_MAX"]) if channel else None
        )
        png, headers = preview_png(path, query, pixels, vmin, vmax, channel_bounds=bounds)
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
        identifiers = list(dict.fromkeys(value for value in ids.split(",") if value))
        if len(identifiers) < 2:
            raise HTTPException(422, "Provide at least two distinct observation ids.")
        entries = [manifest_frame_entry(sky, identifier) for identifier in identifiers]
        parsed = [(search_id, frame_id) for search_id, frame_id, _ in entries]
        detectors = {entry["detector"] for _, _, entry in entries}
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
        if any(
            any(
                sky.manifest(search_id)["query"][key] != getattr(request, key)
                for key in ("ra", "dec", "fov_arcmin")
            )
            for search_id, _ in parsed[1:]
        ):
            warnings.append(
                "Input fields differ. Output uses the first observation's field "
                "center and size; overlap may be incomplete."
            )
        warnings.append(
            "Wavelength can vary between exposures even within one detector. "
            "Moving or variable sources may be blurred by averaging."
        )
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
                "keeping only pixels covered by at least half of them. "
                "Noise reduction depends on coverage and correlated systematics."
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
                    "observedAt": sample.get("observedAt"),
                }
                for sample in samples
            ],
            "fluxUnit": samples[0]["bunit"] if samples else "MJy/sr",
            "extractionMethod": (
                "Single-pixel real flux read directly from one native FITS cutout per "
                "available temporal sample across all six detectors (nearest-pixel, no PSF "
                "photometry or aperture correction), at the exact requested sky position."
            ),
            "sourceLabel": label,
            "warnings": [
                *fingerprint_warnings,
                "Samples span observation dates. Both time and wavelength vary.",
                "This is a single-pixel sample, not PSF-fit or aperture photometry; "
                "nearby bright or flagged pixels are not corrected for.",
            ],
        }

    return router


def frontend_dist():
    return Path(__file__).resolve().parents[3] / "frontend" / "dist"
