"""Regressions for VO status, named science planes, registration, and partial writes."""

import io
from concurrent.futures import ThreadPoolExecutor

import httpx
import numpy as np
import pytest
from astropy.io import fits
from astropy.io.votable import from_table, writeto
from astropy.io.votable.tree import Info, Resource
from astropy.table import Table
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from spherex_api.app import create_app
from spherex_api.archive import ArchiveClient, ArchiveError, cutout_url, parse_sia
from spherex_api.config import Settings
from spherex_api.gaia import GaiaClient
from spherex_api.imaging import inspect_fits, output_wcs, registered_image
from spherex_api.models import SearchRequest
from spherex_api.service import SkyService
from spherex_api.storage import Store

DATA_URL = (
    "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/"
    "2025W18_1B/l2b-v27-2026-196/6/example.fits"
)


def sia_bytes(status="OK", rows=None):
    rows = rows or [
        (DATA_URL, "obs-a", "SPHEREx-D6", "spherex_dr1", 60902.0),
    ]
    base_names = ["access_url", "obs_id", "energy_bandpassname", "obs_collection", "t_min"]
    # Rows may optionally carry (em_min, em_max) in meters, matching the real
    # archive's SIA response, to test wavelength-based grouping/sorting.
    names = [*base_names, "em_min", "em_max"] if len(rows[0]) > len(base_names) else base_names
    table = Table(rows=rows, names=names)
    votable = from_table(table)
    votable.resources[0].type = "results"
    votable.resources[0].infos.append(Info(name="QUERY_STATUS", value=status))
    votable.resources.insert(0, Resource(type="meta"))
    output = io.BytesIO()
    writeto(votable, output)
    return output.getvalue()


def mef_bytes(query, rotation_deg=0, detector=6, center_pixel=(40, 38), wave_crval=4.5):
    pixels = 64
    wcs = output_wcs(query, pixels)
    angle = np.deg2rad(rotation_deg)
    wcs.wcs.pc = [[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]]
    header = wcs.to_header()
    header["DETECTOR"] = detector
    header["OBSID"] = "obs-a"
    header["BUNIT"] = "MJy/sr"
    header["CTYPE1W"] = "WAVE"
    header["CTYPE2W"] = "LINEAR"
    for axis, value in [(1, wave_crval), (2, 0.04)]:
        header[f"CUNIT{axis}W"] = "um"
        header[f"CRPIX{axis}W"] = 32.5
        header[f"CRVAL{axis}W"] = value
        header[f"CDELT{axis}W"] = 0.001
    yy, xx = np.indices((pixels, pixels))
    sky = output_wcs(query, pixels).pixel_to_world(*center_pixel)
    sx, sy = wcs.world_to_pixel(sky)
    image = 20 * np.exp(-((xx - sx) ** 2 + (yy - sy) ** 2) / 5)
    hdus = fits.HDUList(
        [
            fits.PrimaryHDU(),
            # Deliberately place ZODI before IMAGE to catch positional HDU selection.
            fits.ImageHDU(np.full(image.shape, 1000, dtype=np.float32), name="ZODI"),
            fits.ImageHDU(image.astype(np.float32), header=header, name="IMAGE"),
            fits.ImageHDU(np.zeros(image.shape, dtype=np.int32), name="FLAGS"),
            fits.ImageHDU(np.ones(image.shape, dtype=np.float32), name="VARIANCE"),
            fits.BinTableHDU(name="WCS-WAVE"),
        ]
    )
    output = io.BytesIO()
    hdus.writeto(output)
    return output.getvalue()


@pytest.mark.parametrize("ra,dec", [(360, 0), (-1, 0), (0, 91), (float("nan"), 0)])
def test_invalid_coordinates_rejected(ra, dec):
    with pytest.raises(ValidationError):
        SearchRequest(ra=ra, dec=dec)


def test_sexagesimal_and_cutout_geometry():
    query = SearchRequest(ra="08h55m10.831s", dec="-07d14m42.53s", fov_arcmin=10, coverage="field")
    assert query.ra == pytest.approx(133.79512916666665)
    assert query.dec == pytest.approx(-7.245147222222222)
    assert query.radius_deg > 10 / 120
    assert query.cutout_size_deg > 10 / 60 * np.sqrt(2)
    assert "gzip=false" in cutout_url(DATA_URL, query)
    with pytest.raises(ArchiveError):
        cutout_url("https://example.com/image.fits", query)


def test_vo_overflow_and_http_200_error():
    table, overflow = parse_sia(sia_bytes("OVERFLOW"))
    assert len(table) == 1 and overflow
    error = b"""<?xml version="1.0"?>
    <VOTABLE version="1.3" xmlns="http://www.ivoa.net/xml/VOTable/v1.3">
      <RESOURCE type="results"><INFO name="QUERY_STATUS" value="ERROR">bad query</INFO>
      </RESOURCE></VOTABLE>"""
    with pytest.raises(ArchiveError, match="bad query"):
        parse_sia(error)


def test_named_science_plane_and_wavelength():
    query = SearchRequest(ra=133.7, dec=-7.2)
    metadata = inspect_fits(io.BytesIO(mef_bytes(query)), query)
    assert metadata["central_wavelength_um"] == pytest.approx(4.5)
    assert metadata["central_bandwidth_um"] == pytest.approx(0.04)
    assert metadata["science_percentiles_1_50_99"][2] < 20
    assert metadata["nonzero_flag_fraction"] == 0


def test_rotated_star_registers_to_same_sky_pixel(tmp_path):
    query = SearchRequest(ra=359.999, dec=70, fov_arcmin=6)
    for rotation in [0, 37, 90, 170]:
        path = tmp_path / f"rotated-{rotation}.fits"
        path.write_bytes(mef_bytes(query, rotation))
        result = registered_image(path, query, 64)
        y, x = np.unravel_index(np.nanargmax(result), result.shape)
        assert abs(x - 40) <= 1 and abs(y - 38) <= 1
        assert np.nanmax(result) < 21  # ZODI is 1000 in the synthetic MEF.


def test_api_discovery_download_cache_and_png(tmp_path):
    query = SearchRequest(ra=133.7, dec=-7.2)
    calls = []

    def upstream(request):
        calls.append(str(request.url))
        content = sia_bytes() if request.url.path == "/SIA" else mef_bytes(query)
        return httpx.Response(200, content=content)

    settings = Settings(data_dir=tmp_path)
    archive = ArchiveClient(settings, transport=httpx.MockTransport(upstream))
    service = SkyService(settings, archive=archive)
    client = TestClient(create_app(settings, service=service))
    response = client.post("/v1/search", json=query.model_dump(mode="json"))
    assert response.status_code == 200
    manifest = response.json()
    assert manifest["complete"] and not manifest["cache_hit"]
    assert client.get("/v1/search", params={"ra": 133.7, "dec": -7.2}).json()["cache_hit"]
    frame = manifest["frames"][0]
    # Simultaneous requests must produce one complete cached FITS, with one download.
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: service.frame(manifest["search_id"], frame["frame_id"]), range(2))
        )
    assert results[0][1]["sha256"] == results[1][1]["sha256"]
    response = client.get(frame["links"]["fits"])
    assert response.status_code == 200 and response.content.startswith(b"SIMPLE")
    response = client.get(frame["links"]["preview"], params={"vmin": 0, "vmax": 25})
    assert response.status_code == 200
    assert Image.open(io.BytesIO(response.content)).size == (256, 256)
    assert response.headers["x-preview-vmax"] == "25.0"
    assert len(calls) == 2
    assert client.get("/v1/search", params={"ra": "nan", "dec": 0}).status_code == 422
    assert (
        client.post(
            "/v1/search",
            content='{"ra": NaN, "dec": 0}',
            headers={"Content-Type": "application/json"},
        ).status_code
        == 422
    )
    assert client.get(frame["links"]["preview"], params={"vmin": 1}).status_code == 422
    assert client.get("/v1/searches/invalid").status_code == 404


def test_difference_detects_a_moving_source(tmp_path):
    """Two epochs with a source at different pixels should show a red/blue dipole."""
    query = SearchRequest(ra=133.7, dec=-7.2, fov_arcmin=10)
    second_url = DATA_URL.replace("example", "example2")
    rows = [
        (DATA_URL, "obs-a", "SPHEREx-D6", "spherex_dr1", 60900.0),
        (second_url, "obs-b", "SPHEREx-D6", "spherex_dr1", 60901.0),
    ]

    def upstream(request):
        if request.url.path == "/SIA":
            return httpx.Response(200, content=sia_bytes(rows=rows))
        if str(request.url).startswith(second_url):
            return httpx.Response(200, content=mef_bytes(query, center_pixel=(46, 38)))
        return httpx.Response(200, content=mef_bytes(query, center_pixel=(40, 38)))

    settings = Settings(data_dir=tmp_path)
    service = SkyService(settings, ArchiveClient(settings, httpx.MockTransport(upstream)))
    client = TestClient(create_app(settings, service=service))

    response = client.get(
        "/api/observations", params={"ra": 133.7, "dec": -7.2, "fov": 10, "mode": "auto"}
    )
    assert response.status_code == 200
    observations = response.json()["observations"]
    assert len(observations) == 2
    from_id, to_id = observations[0]["id"], observations[1]["id"]

    diff = client.get("/api/difference", params={"fromId": from_id, "toId": to_id, "pixels": 64})
    assert diff.status_code == 200
    body = diff.json()
    assert body["imageUrl"].startswith("/api/difference.png")
    assert any("not" in w.lower() for w in body["warnings"])

    png = client.get(body["imageUrl"])
    assert png.status_code == 200
    image = np.array(Image.open(io.BytesIO(png.content)))
    assert image.shape == (64, 64, 4)
    # The source moved from x=40 to x=46: brighter-now (red) and dimmer-now (blue)
    # separate spatially into a dipole rather than cancelling out.
    assert image[..., 0].max() > 100  # red: brighter in the later frame
    assert image[..., 2].max() > 100  # blue: brighter in the earlier frame

    bad = client.get("/api/difference", params={"fromId": from_id, "toId": "bad"})
    assert bad.status_code == 404


def test_difference_swaps_out_of_order_ids_with_a_warning(tmp_path):
    """Passing fromId/toId chronologically backwards must not invert red/blue."""
    query = SearchRequest(ra=133.7, dec=-7.2, fov_arcmin=10)
    second_url = DATA_URL.replace("example", "example2")
    rows = [
        (DATA_URL, "obs-a", "SPHEREx-D6", "spherex_dr1", 60900.0),
        (second_url, "obs-b", "SPHEREx-D6", "spherex_dr1", 60901.0),
    ]

    def upstream(request):
        if request.url.path == "/SIA":
            return httpx.Response(200, content=sia_bytes(rows=rows))
        if str(request.url).startswith(second_url):
            return httpx.Response(200, content=mef_bytes(query, center_pixel=(46, 38)))
        return httpx.Response(200, content=mef_bytes(query, center_pixel=(40, 38)))

    settings = Settings(data_dir=tmp_path)
    service = SkyService(settings, ArchiveClient(settings, httpx.MockTransport(upstream)))
    client = TestClient(create_app(settings, service=service))

    observations = client.get(
        "/api/observations", params={"ra": 133.7, "dec": -7.2, "fov": 10, "mode": "auto"}
    ).json()["observations"]
    earlier_id, later_id = observations[0]["id"], observations[1]["id"]

    # Deliberately backwards: fromId is the later observation, toId the earlier one.
    diff = client.get(
        "/api/difference", params={"fromId": later_id, "toId": earlier_id, "pixels": 64}
    )
    assert diff.status_code == 200
    assert any("swapped" in w.lower() for w in diff.json()["warnings"])

    png = client.get(diff.json()["imageUrl"])
    image = np.array(Image.open(io.BytesIO(png.content)))
    # Same physical result as calling it in the correct order: red (brighter
    # later) still marks the source's later position, not inverted.
    assert image[..., 0].max() > 100
    assert image[..., 2].max() > 100


def test_difference_warns_on_mismatched_search_grids(tmp_path):
    """Differencing frames whose searches used a different field of view is flagged."""
    narrow = SearchRequest(ra=133.7, dec=-7.2, fov_arcmin=10)
    rows = [(DATA_URL, "obs-a", "SPHEREx-D6", "spherex_dr1", 60900.0)]

    def upstream(request):
        if request.url.path == "/SIA":
            return httpx.Response(200, content=sia_bytes(rows=rows))
        return httpx.Response(200, content=mef_bytes(narrow))

    settings = Settings(data_dir=tmp_path)
    service = SkyService(settings, ArchiveClient(settings, httpx.MockTransport(upstream)))
    client = TestClient(create_app(settings, service=service))

    narrow_id = client.get(
        "/api/observations", params={"ra": 133.7, "dec": -7.2, "fov": 10, "mode": "auto"}
    ).json()["observations"][0]["id"]
    wide_id = client.get(
        "/api/observations", params={"ra": 133.7, "dec": -7.2, "fov": 20, "mode": "auto"}
    ).json()["observations"][0]["id"]

    diff = client.get(
        "/api/difference", params={"fromId": narrow_id, "toId": wide_id, "pixels": 64}
    )
    assert diff.status_code == 200
    warnings = [w.lower() for w in diff.json()["warnings"]]
    assert any("field of view" in w or "field center" in w for w in warnings)

    png = client.get(
        "/api/difference.png", params={"fromId": narrow_id, "toId": wide_id, "pixels": 64}
    )
    assert png.status_code == 200
    assert "x-difference-warning" in {k.lower() for k in png.headers.keys()}


def test_candidates_detects_a_moving_source(tmp_path):
    """A source that shifts between two epochs should come back as a mover."""
    query = SearchRequest(ra=133.7, dec=-7.2, fov_arcmin=10)
    second_url = DATA_URL.replace("example", "example2")
    rows = [
        (DATA_URL, "obs-a", "SPHEREx-D6", "spherex_dr1", 60900.0),
        (second_url, "obs-b", "SPHEREx-D6", "spherex_dr1", 60910.0),
    ]

    def upstream(request):
        if request.url.path == "/SIA":
            return httpx.Response(200, content=sia_bytes(rows=rows))
        if str(request.url).startswith(second_url):
            return httpx.Response(200, content=mef_bytes(query, center_pixel=(46, 38)))
        return httpx.Response(200, content=mef_bytes(query, center_pixel=(40, 38)))

    settings = Settings(data_dir=tmp_path)
    service = SkyService(settings, ArchiveClient(settings, httpx.MockTransport(upstream)))
    client = TestClient(create_app(settings, service=service))

    observations = client.get(
        "/api/observations", params={"ra": 133.7, "dec": -7.2, "fov": 10, "mode": "auto"}
    ).json()["observations"]
    assert len(observations) == 2
    ids = ",".join(o["id"] for o in observations)

    response = client.get(
        "/api/candidates", params={"ra": 133.7, "dec": -7.2, "fov": 10, "ids": ids}
    )
    assert response.status_code == 200
    body = response.json()
    movers = [c for c in body["candidates"] if c["classification"] == "moving-source"]
    assert all(c["caption"] and c["elapsedDays"] > 0 for c in body["candidates"])
    assert all(0 <= c["previousXFraction"] <= 1 for c in movers)
    assert len(movers) >= 1
    mover = movers[0]
    assert mover["displacementArcsec"] > 0
    assert 0 <= mover["xFraction"] <= 1 and 0 <= mover["yFraction"] <= 1
    assert any("unverified" in w.lower() for w in body["warnings"])

    too_few = client.get(
        "/api/candidates",
        params={"ra": 133.7, "dec": -7.2, "fov": 10, "ids": observations[0]["id"]},
    )
    assert too_few.status_code == 422


def test_gaia_overlay_propagates_motion_and_filters_out_of_field(tmp_path):
    """Gaia sources are moved to the observation epoch and clipped to the frame."""
    query = SearchRequest(ra=133.7, dec=-7.2, fov_arcmin=10)
    settings = Settings(data_dir=tmp_path)

    def upstream(request):
        content = sia_bytes() if request.url.path == "/SIA" else mef_bytes(query)
        return httpx.Response(200, content=content)

    service = SkyService(settings, ArchiveClient(settings, httpx.MockTransport(upstream)))

    gaia_columns = [
        {"name": name}
        for name in (
            "source_id",
            "ra",
            "dec",
            "phot_g_mean_mag",
            "pmra",
            "pmdec",
            "parallax",
            "ref_epoch",
        )
    ]
    gaia_rows = [
        # Near the field center, with proper motion: should appear, shifted.
        [111, 133.7, -7.2, 15.0, 200.0, -100.0, 5.0, 2016.0],
        # Nearby but with no astrometric solution: should appear, unshifted.
        [222, 133.701, -7.2, 16.0, None, None, None, 2016.0],
        # Degrees away: should be filtered out as outside the rendered frame.
        [333, 138.7, -7.2, 14.0, 0.0, 0.0, 10.0, 2016.0],
    ]

    def gaia_upstream(request):
        return httpx.Response(200, json={"metadata": gaia_columns, "data": gaia_rows})

    gaia = GaiaClient(settings, transport=httpx.MockTransport(gaia_upstream))
    client = TestClient(create_app(settings, service=service, gaia=gaia))

    observation = client.get(
        "/api/observations", params={"ra": 133.7, "dec": -7.2, "fov": 10, "mode": "auto"}
    ).json()["observations"][0]

    response = client.get("/api/overlays", params={"observationId": observation["id"]})
    assert response.status_code == 200
    body = response.json()
    assert body["catalog"] == "gaia-dr3"
    ids = {s["id"] for s in body["sources"]}
    assert ids == {"111", "222"}  # 333 was outside the field and dropped
    moved = next(s for s in body["sources"] if s["id"] == "111")
    assert moved["raDeg"] != 133.7 and moved["decDeg"] != -7.2  # proper motion applied
    unmoved = next(s for s in body["sources"] if s["id"] == "222")
    assert unmoved["raDeg"] == pytest.approx(133.701) and unmoved["decDeg"] == pytest.approx(-7.2)
    for source in body["sources"]:
        assert 0 <= source["xFraction"] <= 1 and 0 <= source["yFraction"] <= 1
    assert any("proper-motion" in w.lower() for w in body["warnings"])
    assert any("no proper-motion solution" in w.lower() for w in body["warnings"])

    assert client.get("/api/overlays", params={"observationId": "bad"}).status_code == 404
    bad_catalog = client.get(
        "/api/overlays", params={"observationId": observation["id"], "catalog": "wise"}
    )
    assert bad_catalog.status_code == 422


def test_channel_mode_uses_calibrated_window_at_target(tmp_path):
    """Detector-wide SIA bounds cannot identify the wavelength at the target."""
    from spherex_api.frontend import CHANNELS

    query = SearchRequest(ra=133.7, dec=-7.2, fov_arcmin=10)
    count = 17
    waves = [channel["WAVELENGTH"] for channel in CHANNELS[:count]]
    rows = [
        (
            DATA_URL.replace("example", f"example{i}"),
            f"obs-{i}",
            "SPHEREx-D1",
            "spherex_dr1",
            60900.0 + i,
            0.75e-6,
            1.12e-6,
        )
        for i in range(count)
    ]
    urls = {row[0]: i for i, row in enumerate(rows)}

    def upstream(request):
        if request.url.path == "/SIA":
            return httpx.Response(200, content=sia_bytes(rows=rows))
        url = str(request.url)
        for data_url, i in urls.items():
            if url.startswith(data_url):
                return httpx.Response(
                    200, content=mef_bytes(query, detector=1, wave_crval=waves[i])
                )
        raise AssertionError("unexpected URL " + url)

    settings = Settings(data_dir=tmp_path)
    service = SkyService(settings, ArchiveClient(settings, httpx.MockTransport(upstream)))
    client = TestClient(create_app(settings, service=service))

    first = client.get(
        "/api/observations",
        params={"ra": 133.7, "dec": -7.2, "fov": 10, "mode": "channel", "index": 1},
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["selectedDetector"] == 1
    assert len(first_body["observations"]) == 1
    assert any("window" in w.lower() for w in first_body["warnings"])
    assert first_body["observations"][0]["centralWavelengthMicron"] == pytest.approx(
        waves[0], abs=0.003
    )
    assert "channel=1" in first_body["observations"][0]["imageUrl"]

    last = client.get(
        "/api/observations",
        params={"ra": 133.7, "dec": -7.2, "fov": 10, "mode": "channel", "index": 17},
    )
    last_body = last.json()
    assert len(last_body["observations"]) == 1
    # The lowest-wavelength channel and the highest-wavelength channel must be
    # different real exposures, not the same one repeated.
    assert first_body["observations"][0]["id"] != last_body["observations"][0]["id"]

    missing_index = client.get(
        "/api/observations", params={"ra": 133.7, "dec": -7.2, "fov": 10, "mode": "channel"}
    )
    assert missing_index.status_code == 422


def test_combine_averages_exposures_and_warns_on_detector_mismatch(tmp_path):
    """Combining real exposures reduces to an honest coadd, with a mismatch warning."""
    query = SearchRequest(ra=133.7, dec=-7.2, fov_arcmin=10)
    second_url = DATA_URL.replace("example", "example2")
    rows = [
        (DATA_URL, "obs-a", "SPHEREx-D6", "spherex_dr1", 60900.0),
        (second_url, "obs-b", "SPHEREx-D5", "spherex_dr1", 60901.0),
    ]

    def upstream(request):
        if request.url.path == "/SIA":
            return httpx.Response(200, content=sia_bytes(rows=rows))
        if str(request.url).startswith(second_url):
            return httpx.Response(200, content=mef_bytes(query, detector=5))
        return httpx.Response(200, content=mef_bytes(query, detector=6))

    settings = Settings(data_dir=tmp_path)
    service = SkyService(settings, ArchiveClient(settings, httpx.MockTransport(upstream)))
    client = TestClient(create_app(settings, service=service))

    obs6 = client.get(
        "/api/observations",
        params={"ra": 133.7, "dec": -7.2, "fov": 10, "mode": "detector", "index": 6},
    ).json()["observations"]
    obs5 = client.get(
        "/api/observations",
        params={"ra": 133.7, "dec": -7.2, "fov": 10, "mode": "detector", "index": 5},
    ).json()["observations"]
    ids = obs6[0]["id"] + "," + obs5[0]["id"]

    response = client.get("/api/combine", params={"ids": ids, "pixels": 64})
    assert response.status_code == 200
    body = response.json()
    assert body["frameCount"] == 2
    assert any("different detectors" in w.lower() for w in body["warnings"])

    png = client.get(body["imageUrl"])
    assert png.status_code == 200
    assert Image.open(io.BytesIO(png.content)).size == (64, 64)

    too_few = client.get("/api/combine", params={"ids": obs6[0]["id"]})
    assert too_few.status_code == 422
    duplicate = client.get("/api/combine", params={"ids": ",".join([obs6[0]["id"]] * 2)})
    assert duplicate.status_code == 422


def test_spectrum_extracts_real_flux_per_detector(tmp_path):
    """Spectral fingerprint samples real flux at one point across detectors."""
    query = SearchRequest(ra=133.7, dec=-7.2, fov_arcmin=10)
    peak = output_wcs(query, 64).pixel_to_world(40, 38)
    detector_waves = {1: 1.2, 3: 2.8, 6: 4.5}
    urls = {
        detector: DATA_URL.replace("example", f"example-d{detector}") for detector in detector_waves
    }
    rows = [
        (
            urls[d],
            f"obs-d{d}",
            f"SPHEREx-D{d}",
            "spherex_dr1",
            60900.0,
            detector_waves[d] * 1e-6,
            detector_waves[d] * 1e-6,
        )
        for d in detector_waves
    ]

    def upstream(request):
        if request.url.path == "/SIA":
            return httpx.Response(200, content=sia_bytes(rows=rows))
        url = str(request.url)
        for d, data_url in urls.items():
            if url.startswith(data_url):
                return httpx.Response(
                    200, content=mef_bytes(query, detector=d, wave_crval=detector_waves[d])
                )
        raise AssertionError("unexpected URL " + url)

    settings = Settings(data_dir=tmp_path)
    service = SkyService(settings, ArchiveClient(settings, httpx.MockTransport(upstream)))
    client = TestClient(create_app(settings, service=service))

    response = client.get("/api/spectrum", params={"ra": peak.ra.deg, "dec": peak.dec.deg})
    assert response.status_code == 200
    body = response.json()
    assert len(body["samples"]) == 3
    waves = [s["wavelengthMicron"] for s in body["samples"]]
    assert waves == sorted(waves)
    assert waves[0] == pytest.approx(1.2, abs=0.05)
    assert waves[-1] == pytest.approx(4.5, abs=0.05)
    for sample in body["samples"]:
        assert sample["flux"] > 15  # near the Gaussian peak (amplitude 20)
        assert sample["uncertainty"] is not None
    assert body["fluxUnit"] == "MJy/sr"
    assert body["extractionMethod"]

    far = client.get("/api/spectrum", params={"ra": 1, "dec": 0})
    assert far.status_code == 200
    far_body = far.json()
    assert far_body["samples"] == []
    assert any("covered this exact sky position" in w.lower() for w in far_body["warnings"])

    assert client.get("/api/spectrum").status_code == 422


def test_coadd_requires_ceiling_half_coverage(monkeypatch):
    from spherex_api import imaging

    arrays = [np.ones((2, 2)) * value for value in range(5)]
    for array in arrays[2:]:
        array[0, 0] = np.nan
    for array in arrays[3:]:
        array[0, 1] = np.nan
    monkeypatch.setattr(imaging, "registered_image", lambda path, *args: arrays[path])
    query = SearchRequest(ra=1, dec=0)
    combined, counts = imaging.combine_registered(list(range(5)), query, pixels=2)
    assert counts[0, 0] == 2
    assert np.isnan(combined[0, 0])
    assert counts[0, 1] == 3
    assert combined[0, 1] == pytest.approx(1)
    assert combined[1, 1] == pytest.approx(2)


def test_failed_download_is_not_committed(tmp_path):
    settings = Settings(data_dir=tmp_path)

    def upstream(request):
        return httpx.Response(
            200, content=sia_bytes() if request.url.path == "/SIA" else b"<html>error</html>"
        )

    service = SkyService(settings, ArchiveClient(settings, httpx.MockTransport(upstream)))
    manifest = service.search(SearchRequest(ra=1, dec=0))
    frame = manifest["frames"][0]
    with pytest.raises(ArchiveError):
        service.frame(manifest["search_id"], frame["frame_id"])
    assert not service.store.path("cutouts", frame["frame_id"], ".fits").exists()


def test_budget_preserves_previous_product(tmp_path):
    from spherex_api.archive import CapacityError

    store = Store(Settings(data_dir=tmp_path, cache_budget_bytes=10))
    path = tmp_path / "product"
    store.write_bytes(path, b"1234567890")
    with pytest.raises(CapacityError):
        store.write_bytes(path, b"this would exceed budget")
    assert path.read_bytes() == b"1234567890"


def test_unchanged_frontend_contract(tmp_path):
    query = SearchRequest(ra=133.7, dec=-7.2, fov_arcmin=10)
    settings = Settings(data_dir=tmp_path)

    def upstream(request):
        content = sia_bytes() if request.url.path == "/SIA" else mef_bytes(query)
        return httpx.Response(200, content=content)

    service = SkyService(settings, ArchiveClient(settings, httpx.MockTransport(upstream)))
    client = TestClient(create_app(settings, service))
    for name in ["Barnard's Star", "Epsilon Indi B", "WISE 0855", "RW Aurigae", "R Draconis"]:
        response = client.get("/api/resolve", params={"name": name})
        assert response.status_code == 200 and isinstance(response.json()["raDeg"], float)
    response = client.get(
        "/api/observations", params={"ra": 133.7, "dec": -7.2, "fov": 10, "mode": "auto"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["selectedDetector"] == 6
    observation = data["observations"][0]
    assert observation["imageAligned"] and observation["imageUrl"].startswith("/api/images/")
    assert "vmin=" in observation["imageUrl"] and observation["detector"] == 6
    assert observation["flags"] == []
    response = client.get(observation["imageUrl"])
    assert response.status_code == 200
    assert Image.open(io.BytesIO(response.content)).size == (512, 512)
    assert client.get("/api/images/invalid.png").status_code == 404
    assert client.get("/api/spectrum").status_code == 422
    for params in [
        {"ra": 1, "dec": 0, "mode": "detector", "index": 7},
        {"ra": "nan", "dec": 0},
    ]:
        assert client.get("/api/observations", params=params).status_code == 422
    # ra=1,dec=0 is outside the synthetic frame's footprint, so no exposure's
    # wavelength can be measured there: channel mode degrades to an honest
    # empty result instead of fabricating channel data.
    far_channel = client.get(
        "/api/observations", params={"ra": 1, "dec": 0, "mode": "channel", "index": 102}
    )
    assert far_channel.status_code == 200
    assert far_channel.json()["observations"] == []
    assert (
        client.get("/api/observations", params={"ra": 1, "dec": 0, "mode": "channel"}).status_code
        == 422
    )
    assert SearchRequest(ra=0, dec=0, fov_arcmin=60).fov_arcmin == 60
