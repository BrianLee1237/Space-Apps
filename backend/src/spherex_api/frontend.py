"""Compatibility routes for the existing, unchanged React frontend."""

import re
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from .imaging import difference_png, preview_png
from .models import SearchRequest
from .targets import TARGETS


def observation_parts(identifier):
    if not re.fullmatch(r"[a-f0-9]{24}\.[a-f0-9]{24}", identifier):
        raise KeyError(identifier)
    return identifier.split(".")


def frontend_router(sky):
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

    @router.get("/observations")
    def observations(
        ra: Annotated[float, Query(ge=0, lt=360, allow_inf_nan=False)],
        dec: Annotated[float, Query(ge=-90, le=90, allow_inf_nan=False)],
        fov: Annotated[float, Query(ge=0.5, le=60, allow_inf_nan=False)] = 10,
        mode: Literal["auto", "detector", "channel"] = "auto",
        index: Annotated[int | None, Query(ge=1, le=102)] = None,
    ):
        if mode == "channel":
            raise HTTPException(501, "Nominal-channel image sequences require spectral binning.")
        if mode == "detector" and (index is None or index > 6):
            raise HTTPException(422, "Detector mode requires index between 1 and 6.")
        # A single detector keeps the initial animation within one detector bandpass.
        detector = index if mode == "detector" else 6
        query = SearchRequest(ra=ra, dec=dec, fov_arcmin=fov, detectors=(detector,))
        manifest = sky.search(query)
        if not manifest["complete"]:
            raise HTTPException(
                422, "The archive truncated this search. Use /v1/search with a narrower time range."
            )
        frames = manifest["frames"]
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
        from_search, from_frame = observation_parts(fromId)
        to_search, to_frame = observation_parts(toId)
        _, from_metadata = sky.frame(from_search, from_frame)
        _, to_metadata = sky.frame(to_search, to_frame)
        warnings = [
            "Not a flux-calibrated difference image: no PSF matching or background fitting.",
            "Residuals near bright, saturated, or flagged pixels are not scientifically validated.",
        ]
        if from_metadata["detector"] != to_metadata["detector"]:
            warnings.append(
                "The two frames use different detectors with different bandpasses; "
                "the subtraction mixes wavelength coverage."
            )
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
        from_search, from_frame = observation_parts(fromId)
        to_search, to_frame = observation_parts(toId)
        path_from, _ = sky.frame(from_search, from_frame)
        path_to, _ = sky.frame(to_search, to_frame)
        request = SearchRequest.model_validate(sky.manifest(from_search)["query"])
        png, headers = difference_png(
            path_from, path_to, request, pixels, reject_bits, subtract_zodi
        )
        return Response(png, media_type="image/png", headers=headers)

    @router.get("/spectrum")
    @router.get("/candidates")
    @router.get("/overlays")
    def pending_science_product():
        raise HTTPException(
            501, "This scientific product is pending implementation and validation."
        )

    return router


def frontend_dist():
    return Path(__file__).resolve().parents[3] / "frontend" / "dist"
