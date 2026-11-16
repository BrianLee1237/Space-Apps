"""Expose individual IRSA cube layers as standard two-dimensional HiPS surveys."""

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import RedirectResponse, Response

from .archive import ArchiveError
from .photometry import CHANNELS

IRSA_CUBE = "https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube"
Channel = Annotated[int, Path(ge=1, le=102)]


def atlas_router(archive):
    router = APIRouter()

    @lru_cache(maxsize=1)
    def source_properties():
        text = archive.fetch(IRSA_CUBE + "/properties").decode("utf-8")
        return dict(
            line.split("=", 1)
            for line in text.splitlines()
            if "=" in line and not line.startswith("#")
        )

    @router.get("/{channel}/properties")
    def properties(channel: Channel, request: Request):
        try:
            original = source_properties()
        except ArchiveError as exc:
            raise HTTPException(502, str(exc)) from exc
        values = {key.strip(): value.strip() for key, value in original.items()}
        # Aladin's frequency interpolation does not follow this cube's irregular
        # wavelength array. Each layer gets an explicit image-survey tile mapping.
        values = {
            key: value
            for key, value in values.items()
            if not key.startswith(("hips_cube_", "data_cube_", "custom_tile_"))
            and key not in {"hips_pixel_cut", "hips_pixel_function", "hips_progenitor_url"}
        }
        calibration = CHANNELS[channel - 1]
        values.update(
            dataproduct_type="image",
            creator_did=f"ivo://IPAC/P/SPHEREx/DR1/channel/{channel}",
            obs_title=f"SPHEREx DR1 channel {channel}",
            hips_service_url=str(request.url).rsplit("/", 1)[0],
            em_min=str(calibration["WL_MIN"] * 1e-6),
            em_max=str(calibration["WL_MAX"] * 1e-6),
        )
        return Response(
            "\n".join(f"{key} = {value}" for key, value in values.items()),
            media_type="text/plain",
            headers={"Cache-Control": "public, max-age=900"},
        )

    @router.get("/{channel}/Norder{order}/Dir{directory}/Npix{pixel}.png")
    def tile(channel: Channel, order: int, directory: int, pixel: int):
        if not 0 <= order <= 5 or not 0 <= pixel < 12 * 4**order:
            raise HTTPException(404, "Unknown HiPS tile")
        if directory != pixel // 10000 * 10000:
            raise HTTPException(404, "Unknown HiPS tile directory")
        suffix = f"_{channel - 1}" if channel > 1 else ""
        return RedirectResponse(
            f"{IRSA_CUBE}/Norder{order}/Dir{directory}/Npix{pixel}{suffix}.png",
            status_code=307,
            headers={"Cache-Control": "public, max-age=900"},
        )

    return router
