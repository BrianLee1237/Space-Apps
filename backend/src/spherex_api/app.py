import logging
import math
import os
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from filelock import Timeout as LockTimeout
from pydantic import ValidationError

from .archive import ArchiveError, CapacityError
from .config import Settings
from .frontend import frontend_dist, frontend_router
from .gaia import GaiaClient
from .imaging import preview_png
from .models import Collection, SearchRequest
from .service import SkyService
from .targets import TARGETS

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, service=None, gaia=None):
    settings = settings or Settings.from_env()
    sky = service or SkyService(settings)
    gaia = gaia or GaiaClient(settings)
    app = FastAPI(
        title="SPHEREx Sky API",
        version="0.1.0",
        description=(
            "Anonymous public-data discovery, native FITS cutouts, quality metadata, "
            "and registered quick-look previews. Coordinates use ICRS. "
            "Times use UTC Modified Julian Date. No NASA API key is needed."
        ),
    )
    app.state.sky = sky
    origins = [v.strip() for v in os.getenv("SPHEREX_CORS_ORIGINS", "").split(",") if v.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
            expose_headers=[
                "X-Preview-Vmin",
                "X-Preview-Vmax",
                "X-Preview-Valid-Fraction",
                "X-Preview-Scale",
                "X-Preview-Orientation",
                "X-Preview-Zodi-Subtracted",
                "X-Difference-Vmax",
                "X-Difference-Scale",
                "X-Difference-Warning",
            ],
        )

    @app.exception_handler(ArchiveError)
    def archive_error(request: Request, exc: ArchiveError):
        logger.warning("Archive error: %s", exc)
        return JSONResponse(status_code=502, content={"detail": str(exc), "retryable": True})

    @app.exception_handler(RequestValidationError)
    def invalid_request(request: Request, exc: RequestValidationError):
        errors = [{key: error[key] for key in ("type", "loc", "msg")} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(CapacityError)
    @app.exception_handler(LockTimeout)
    def capacity_error(request: Request, exc):
        return JSONResponse(
            status_code=503, content={"detail": str(exc)}, headers={"Retry-After": "5"}
        )

    @app.exception_handler(KeyError)
    def missing(request: Request, exc: KeyError):
        return JSONResponse(status_code=404, content={"detail": "Unknown search or frame"})

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "0.1.0", "archive_checked": False}

    @app.get("/v1/capabilities")
    def capabilities():
        return {
            "archive_credentials_required": False,
            "collections": ["spherex_dr1", "spherex_qr3", "spherex_dr1_deep", "spherex_qr3_deep"],
            "default_collections": ["spherex_dr1", "spherex_qr3"],
            "fov_arcmin_bounds": [0.5, 60],
            "search_cache_seconds": settings.search_ttl_seconds,
            "max_download_bytes": settings.max_response_bytes,
            "cache_budget_bytes": settings.cache_budget_bytes,
            "image_products": ["native_multi_extension_fits", "registered_quicklook_png"],
            "science_difference_imaging": True,
            "gaia_dr3_overlay": True,
            "candidate_detection": True,
            "calibrated_spectrum_extraction": False,
            "quicklook_surface_brightness_spectrum": True,
            "channel_wavelength_windows": 102,
        }

    @app.get("/v1/targets")
    def targets():
        return TARGETS

    @app.post("/v1/search")
    def post_search(query: SearchRequest, refresh: bool = False):
        return sky.search(query, refresh=refresh)

    @app.get("/v1/search")
    def get_search(
        ra: str,
        dec: str,
        fov_arcmin: float = 6,
        coverage: Literal["center", "field"] = "center",
        collections: Annotated[list[Collection] | None, Query()] = None,
        detectors: Annotated[list[int] | None, Query()] = None,
        mjd_min: float | None = None,
        mjd_max: float | None = None,
        max_records: int = 10000,
        refresh: bool = False,
    ):
        values = {
            "ra": ra,
            "dec": dec,
            "fov_arcmin": fov_arcmin,
            "coverage": coverage,
            "mjd_min": mjd_min,
            "mjd_max": mjd_max,
            "max_records": max_records,
        }
        if collections is not None:
            values["collections"] = collections
        if detectors is not None:
            values["detectors"] = detectors
        try:
            query = SearchRequest.model_validate(values)
        except ValidationError as exc:
            # Pydantic error contexts may contain non-JSON exceptions.
            raise HTTPException(
                422, detail=exc.errors(include_context=False, include_input=False)
            ) from exc
        return sky.search(query, refresh=refresh)

    @app.get("/v1/searches/{search_id}")
    def manifest(search_id: str):
        return sky.manifest(search_id)

    @app.get("/v1/searches/{search_id}/frames/{frame_id}")
    def frame_metadata(search_id: str, frame_id: str):
        return sky.frame(search_id, frame_id)[1]

    @app.get("/v1/searches/{search_id}/frames/{frame_id}/fits")
    def frame_fits(search_id: str, frame_id: str):
        path, metadata = sky.frame(search_id, frame_id)
        return FileResponse(
            path,
            media_type="application/fits",
            filename=f"spherex-{frame_id}.fits",
            headers={"X-Content-SHA256": metadata["sha256"]},
        )

    @app.get("/v1/searches/{search_id}/frames/{frame_id}/preview.png")
    def frame_preview(
        search_id: str,
        frame_id: str,
        pixels: Annotated[int, Query(ge=32, le=1024)] = 256,
        vmin: float | None = None,
        vmax: float | None = None,
        reject_bits: Annotated[int, Query(ge=0, le=2**32 - 1)] = 0,
        subtract_zodi: bool = False,
    ):
        if (vmin is None) != (vmax is None) or (
            vmin is not None
            and (not math.isfinite(vmin) or not math.isfinite(vmax) or vmin >= vmax)
        ):
            raise HTTPException(422, "Supply both finite vmin and vmax, with vmin < vmax")
        path, _ = sky.frame(search_id, frame_id)
        query = SearchRequest.model_validate(sky.manifest(search_id)["query"])
        payload, headers = preview_png(path, query, pixels, vmin, vmax, reject_bits, subtract_zodi)
        return Response(payload, media_type="image/png", headers=headers)

    app.include_router(frontend_router(sky, gaia))
    distribution = frontend_dist()
    if distribution.is_dir():
        app.mount("/", StaticFiles(directory=distribution, html=True), name="frontend")
    return app


app = create_app()
