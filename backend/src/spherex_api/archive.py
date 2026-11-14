"""A bounded, read-only SIA2 adapter, with explicit VO error/overflow handling."""

import io
import math
import re
import threading
import time
from urllib.parse import urlencode, urlsplit

import httpx
import numpy as np
from astropy.io.votable import parse
from astropy.time import Time

from .config import Settings
from .models import SearchRequest

SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
DATA_PREFIX = "/ibe/data/spherex/"


class ArchiveError(RuntimeError):
    pass


class CapacityError(RuntimeError):
    pass


def trusted_data_url(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.netloc != "irsa.ipac.caltech.edu"
        or not parts.path.startswith(DATA_PREFIX)
        or not parts.path.endswith(".fits")
        or parts.query
        or parts.fragment
        or "/../" in parts.path
        or "%" in parts.path
    ):
        raise ArchiveError("Archive returned an unsupported data URL")
    return url


def cutout_url(url: str, request: SearchRequest) -> str:
    return (
        trusted_data_url(url)
        + "?"
        + urlencode(
            {
                "center": f"{request.ra:.10f},{request.dec:.10f}d",
                "size": f"{request.cutout_size_deg:.10f}",
                "gzip": "false",
            }
        )
    )


def scalar(value):
    if np.ma.is_masked(value):
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def parse_sia(payload: bytes):
    try:
        votable = parse(io.BytesIO(payload), verify="warn")
    except Exception as exc:
        raise ArchiveError("IRSA did not return a valid VOTable") from exc
    overflow = False
    tables = []

    def visit(resources):
        nonlocal overflow
        for resource in resources:
            for info in resource.infos:
                if info.name == "QUERY_STATUS":
                    if info.value == "ERROR":
                        raise ArchiveError(
                            f"IRSA query failed: {info.content or 'unknown VO error'}"
                        )
                    overflow |= info.value == "OVERFLOW"
            if resource.type == "results":
                tables.extend(resource.tables)
            visit(resource.resources)

    visit(votable.resources)
    if len(tables) != 1:
        raise ArchiveError("Expected one SIA results table")
    table = tables[0].to_table(use_names_over_ids=True)
    required = {"access_url", "obs_id", "energy_bandpassname", "obs_collection", "t_min"}
    if not required.issubset(table.colnames):
        raise ArchiveError("IRSA result schema changed: required columns are missing")
    return table, overflow


class ArchiveClient:
    def __init__(self, settings: Settings, transport=None):
        self.settings = settings
        self.transport = transport
        self.slots = threading.BoundedSemaphore(settings.archive_concurrency)

    def fetch(self, url, params=None) -> bytes:
        if not self.slots.acquire(timeout=1):
            raise CapacityError("Archive request capacity is busy; try again shortly")
        try:
            for attempt in range(self.settings.retries + 1):
                try:
                    with httpx.Client(
                        timeout=httpx.Timeout(self.settings.timeout_seconds, connect=20),
                        follow_redirects=False,
                        transport=self.transport,
                        headers={"User-Agent": "SPHERExSkyAPI/0.1 (public-data prototype)"},
                    ) as client:
                        with client.stream("GET", url, params=params) as response:
                            response.raise_for_status()
                            chunks = []
                            size = 0
                            for chunk in response.iter_bytes():
                                size += len(chunk)
                                if size > self.settings.max_response_bytes:
                                    raise ArchiveError(
                                        "Archive response exceeds the configured byte limit"
                                    )
                                chunks.append(chunk)
                            return b"".join(chunks)
                except httpx.HTTPStatusError as exc:
                    retry = exc.response.status_code in {429, 500, 502, 503, 504}
                    if not retry or attempt == self.settings.retries:
                        raise ArchiveError(
                            f"IRSA returned HTTP {exc.response.status_code}"
                        ) from exc
                except httpx.TransportError as exc:
                    if attempt == self.settings.retries:
                        raise ArchiveError("IRSA network request failed or timed out") from exc
                time.sleep(min(2**attempt, 4))
        finally:
            self.slots.release()

    def search(self, request: SearchRequest):
        params = [
            ("POS", f"CIRCLE {request.ra:.8f} {request.dec:.8f} {request.radius_deg:.8f}"),
            ("MAXREC", str(request.max_records)),
        ]
        params.extend(("COLLECTION", c) for c in request.collections)
        if request.mjd_min is not None or request.mjd_max is not None:
            low = request.mjd_min if request.mjd_min is not None else "-Inf"
            high = request.mjd_max if request.mjd_max is not None else "+Inf"
            params.append(("TIME", f"{low} {high}"))
        table, overflow = parse_sia(self.fetch(SIA_URL, params))
        frames = {}
        for row in table:
            band = str(row["energy_bandpassname"])
            match = re.fullmatch(r"SPHEREx-D([1-6])", band)
            if not match or int(match[1]) not in request.detectors:
                continue
            raw = {name: scalar(row[name]) for name in table.colnames}
            url = trusted_data_url(raw["access_url"])
            mjd = raw["t_min"]
            if mjd is None:
                raise ArchiveError("An observation is missing its observation time")
            frames[url] = {
                "access_url": url,
                "cutout_url": cutout_url(url, request),
                "obs_id": raw["obs_id"],
                "collection": raw["obs_collection"],
                "detector": int(match[1]),
                "mjd_start": mjd,
                "mjd_end": raw.get("t_max"),
                "observed_at_utc": Time(mjd, format="mjd", scale="utc").isot + "Z",
                "detector_wavelength_min_um": (raw.get("em_min") or 0) * 1e6,
                "detector_wavelength_max_um": (raw.get("em_max") or 0) * 1e6,
                "archive_metadata": raw,
            }
        return (
            sorted(frames.values(), key=lambda f: (f["mjd_start"], f["detector"], f["access_url"])),
            overflow or len(table) >= request.max_records,
            len(table),
            params,
        )
