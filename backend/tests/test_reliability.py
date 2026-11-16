"""Regressions for upstream outages, real-catalog fallbacks, and damaged cache entries."""

import io
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from astropy.io.votable import from_table, writeto
from astropy.table import Table
from fastapi.testclient import TestClient
from test_science_and_api import DATA_URL, mef_bytes, sia_bytes

from spherex_api.app import create_app
from spherex_api.archive import SIA_URL, ArchiveClient, ArchiveError
from spherex_api.config import Settings
from spherex_api.gaia import GaiaClient, gaia_overlay
from spherex_api.models import SearchRequest
from spherex_api.service import SkyService
from spherex_api.storage import canonical, digest


def gaia_votable():
    table = Table(
        rows=[(1234567891234567890, 133.7, -7.2, 14.2, 1.0, -2.0, 5.0)],
        names=("Source", "RA_ICRS", "DE_ICRS", "Gmag", "pmRA", "pmDE", "Plx"),
    )
    stream = io.BytesIO()
    writeto(from_table(table), stream)
    return stream.getvalue()


def test_vizier_cones_are_shared_between_threads_and_restarts(tmp_path):
    calls = []

    def upstream(request):
        calls.append(request.url.host)
        assert request.url.host == "vizier.cfa.harvard.edu"
        time.sleep(0.03)
        return httpx.Response(200, content=gaia_votable())

    settings = Settings(data_dir=tmp_path)
    transport = httpx.MockTransport(upstream)
    client = GaiaClient(settings, transport=transport)
    with ThreadPoolExecutor(4) as pool:
        rows = list(pool.map(lambda _: client.cone_search(133.7, -7.2, 0.1, 75), range(4)))
    assert len(calls) == 1
    assert rows[0][1][0][0] == "1234567891234567890"
    assert rows[0][1][0][-1] == 2016.0
    assert GaiaClient(settings, transport=transport).cone_search(133.7, -7.2, 0.1, 75) == rows[0]
    assert len(calls) == 1


def test_stale_gaia_rows_remain_available_with_an_explicit_warning(tmp_path):
    settings = Settings(data_dir=tmp_path)
    client = GaiaClient(
        settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=gaia_votable())),
    )
    query = SearchRequest(ra=133.7, dec=-7.2, fov_arcmin=10)
    gaia_overlay(client, query, "2025-01-01T00:00:00Z")
    for path in (tmp_path / "catalogs").glob("*.json"):
        record = client.store.read("catalogs", path.stem)
        record["retrievedUnix"] = 0
        client.store.write("catalogs", path.stem, record)
    offline = GaiaClient(
        settings, transport=httpx.MockTransport(lambda request: httpx.Response(503))
    )
    sources, warnings = gaia_overlay(offline, query, "2025-01-01T00:00:00Z")
    assert len(sources) == 1
    assert any("previously retrieved" in warning for warning in warnings)
    assert any("Harvard VizieR" in warning for warning in warnings)


def test_saved_search_survives_outage_and_old_float_serialization(tmp_path):
    calls = []
    online = True

    def upstream(request):
        calls.append(request.url.path)
        return httpx.Response(200, content=sia_bytes()) if online else httpx.Response(502)

    settings = Settings(data_dir=tmp_path, retries=0, search_ttl_seconds=0)
    service = SkyService(settings, ArchiveClient(settings, httpx.MockTransport(upstream)))
    query = SearchRequest(ra=133.79512916666665, dec=-7.245147222222222, detectors=(6,))
    original = service.search(query)
    old_key = digest(canonical(query.model_dump(mode="json")))
    service.store.write("queries", old_key, {"search_id": original["search_id"], "created_unix": 0})
    service.store.path("queries", service.query_key(query)).unlink()
    online = False
    equivalent = query.model_copy(update={"ra": 133.79512916666664})
    recovered = service.search(equivalent)
    assert recovered["search_id"] == original["search_id"]
    assert recovered["stale"] is True
    assert any("New observations may be absent" in warning for warning in recovered["warnings"])
    assert len(calls) == 2
    assert service.search(equivalent)["stale"] is True
    assert len(calls) == 2  # Cooldown avoids repeatedly hitting a failed upstream.


def test_first_cutout_failure_keeps_the_sequence_and_uses_a_readable_epoch(tmp_path):
    query = SearchRequest(ra=133.7, dec=-7.2, fov_arcmin=10, detectors=(6,))
    second = DATA_URL.replace("example", "second")

    def upstream(request):
        if request.url.path == "/SIA":
            return httpx.Response(
                200,
                content=sia_bytes(
                    rows=[
                        (DATA_URL, "first", "SPHEREx-D6", "spherex_dr1", 60900),
                        (second, "second", "SPHEREx-D6", "spherex_dr1", 60930),
                    ]
                ),
            )
        if request.url.path.endswith("example.fits"):
            return httpx.Response(503)
        return httpx.Response(200, content=mef_bytes(query))

    settings = Settings(data_dir=tmp_path, retries=0)
    service = SkyService(settings, ArchiveClient(settings, httpx.MockTransport(upstream)))
    with TestClient(create_app(settings, service=service)) as client:
        response = client.get("/api/observations", params={"ra": query.ra, "dec": query.dec})
        assert response.status_code == 200
        data = response.json()
        assert len(data["observations"]) == 2
        assert data["initialObservationId"] == data["observations"][1]["id"]
        assert any("trying another" in warning.lower() for warning in data["warnings"])
        assert client.get(data["observations"][1]["imageUrl"]).status_code == 200


def test_damaged_fits_cache_is_repaired_from_the_original_observation(tmp_path):
    query = SearchRequest(ra=133.7, dec=-7.2, detectors=(6,))
    downloads = []

    def upstream(request):
        if request.url.path == "/SIA":
            return httpx.Response(200, content=sia_bytes())
        downloads.append(request.url.path)
        return httpx.Response(200, content=mef_bytes(query))

    settings = Settings(data_dir=tmp_path)
    service = SkyService(settings, ArchiveClient(settings, httpx.MockTransport(upstream)))
    manifest = service.search(query)
    frame = manifest["frames"][0]["frame_id"]
    path, original = service.frame(manifest["search_id"], frame)
    damaged = bytearray(path.read_bytes())
    damaged[100] ^= 1
    path.write_bytes(damaged)
    repaired, metadata = service.frame(manifest["search_id"], frame)
    assert repaired == path
    assert metadata["sha256"] == original["sha256"]
    assert len(downloads) == 2
    assert service.manifest(manifest["search_id"])["frame_count"] == 1


def test_gaia_overlay_is_independent_of_fits_downloads(tmp_path, monkeypatch):
    query = SearchRequest(ra=133.7, dec=-7.2, detectors=(6,))
    settings = Settings(data_dir=tmp_path)
    archive = ArchiveClient(
        settings, httpx.MockTransport(lambda request: httpx.Response(200, content=sia_bytes()))
    )
    service = SkyService(settings, archive)
    manifest = service.search(query)
    identifier = manifest["search_id"] + "." + manifest["frames"][0]["frame_id"]
    gaia = GaiaClient(
        settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=gaia_votable())),
        store=service.store,
    )

    def unavailable(*args):
        raise ArchiveError("FITS server is unavailable")

    monkeypatch.setattr(service, "frame", unavailable)
    with TestClient(create_app(settings, service=service, gaia=gaia)) as client:
        response = client.get("/api/overlays", params={"observationId": identifier})
        assert response.status_code == 200
        assert len(response.json()["sources"]) == 1
        from test_science_workbench import wait_for_job

        submitted = client.post(
            "/api/science/jobs",
            json={
                "kind": "catalog",
                "ids": [identifier],
                "referenceId": identifier,
            },
        )
        job = wait_for_job(client, submitted)
        assert job["state"] == "complete", job
        assert len(job["result"]["counterparts"]) == 1


def test_invalid_fits_response_has_a_retryable_archive_error(tmp_path):
    settings = Settings(data_dir=tmp_path, retries=0)
    archive = ArchiveClient(
        settings,
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=sia_bytes() if request.url.path == "/SIA" else b"<html>maintenance</html>",
            )
        ),
    )
    service = SkyService(settings, archive)
    with TestClient(create_app(settings, service=service)) as client:
        data = client.get("/api/observations", params={"ra": 133.7, "dec": -7.2}).json()
        response = client.get(data["observations"][0]["imageUrl"])
        assert response.status_code == 502
        assert "invalid SPHEREx FITS" in response.json()["detail"]


def test_archive_retry_after_and_search_time_budget(tmp_path, monkeypatch):
    attempts, delays = [], []

    def upstream(request):
        attempts.append(request)
        return (
            httpx.Response(429, headers={"Retry-After": "3"})
            if len(attempts) == 1
            else httpx.Response(200, content=b"ok")
        )

    monkeypatch.setattr("spherex_api.archive.time.sleep", delays.append)
    archive = ArchiveClient(Settings(data_dir=tmp_path), httpx.MockTransport(upstream))
    assert archive.fetch(SIA_URL) == b"ok"
    assert delays == [3]
    assert attempts[0].extensions["timeout"]["read"] <= 25


def test_cors_supports_cancelling_science_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("SPHEREX_CORS_ORIGINS", "https://viewer.example")
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        response = client.options(
            "/api/science/jobs/example/subscriber",
            headers={
                "Origin": "https://viewer.example",
                "Access-Control-Request-Method": "DELETE",
            },
        )
        assert response.status_code == 200
        assert "DELETE" in response.headers["access-control-allow-methods"]


def test_field_size_reuses_real_discovery_but_requests_new_cutouts(tmp_path):
    calls = []
    online = True

    def upstream(request):
        calls.append(request.url.path)
        return httpx.Response(200, content=sia_bytes()) if online else httpx.Response(502)

    settings = Settings(data_dir=tmp_path, retries=0, search_ttl_seconds=0)
    service = SkyService(settings, ArchiveClient(settings, httpx.MockTransport(upstream)))
    query = SearchRequest(ra=133.7, dec=-7.2, fov_arcmin=6, detectors=(6,))
    original = service.search(query)
    online = False
    expanded = service.search(query.model_copy(update={"fov_arcmin": 12}))
    assert expanded["stale"] is True
    assert expanded["created_at_utc"] == original["created_at_utc"]
    assert expanded["query"]["fov_arcmin"] == 12
    assert expanded["frames"][0]["access_url"] == original["frames"][0]["access_url"]
    assert expanded["frames"][0]["cutout_url"] != original["frames"][0]["cutout_url"]
    assert expanded["frames"][0]["frame_id"] != original["frames"][0]["frame_id"]
    assert len(calls) == 2


def test_science_jobs_defer_downloads_after_repeated_failures(tmp_path):
    from test_science_workbench import wait_for_job

    query = SearchRequest(ra=133.7, dec=-7.2, detectors=(6,))
    failures = []
    rows = [
        (
            DATA_URL.replace("example", f"example-{i}"),
            str(i),
            "SPHEREx-D6",
            "spherex_dr1",
            60900 + i,
        )
        for i in range(10)
    ]

    def upstream(request):
        if request.url.path == "/SIA":
            return httpx.Response(200, content=sia_bytes(rows=rows))
        if request.url.path.endswith("example-0.fits"):
            return httpx.Response(200, content=mef_bytes(query))
        failures.append(request.url.path)
        return httpx.Response(503)

    settings = Settings(data_dir=tmp_path, retries=0)
    service = SkyService(settings, ArchiveClient(settings, httpx.MockTransport(upstream)))
    with TestClient(create_app(settings, service=service)) as client:
        data = client.get("/api/observations", params={"ra": query.ra, "dec": query.dec}).json()
        ids = [row["id"] for row in data["observations"]]
        submitted = client.post(
            "/api/science/jobs", json={"kind": "matches", "ids": ids, "referenceId": ids[0]}
        )
        job = wait_for_job(client, submitted)
        assert job["state"] == "complete", job
        assert job["result"]["inspected"] == 1
        assert len(failures) == 3
        assert any("Deferred 6" in warning for warning in job["result"]["warnings"])


def test_unseen_sky_coordinates_open_atlas_when_discovery_is_down(tmp_path):
    settings = Settings(data_dir=tmp_path, retries=0)
    archive = ArchiveClient(settings, httpx.MockTransport(lambda request: httpx.Response(502)))
    service = SkyService(settings, archive)
    with TestClient(create_app(settings, service=service)) as client:
        result = client.get("/api/observations", params={"ra": 17, "dec": 6})
        assert result.status_code == 200
        assert result.json()["fallback"] == "atlas"
        assert result.json()["observations"] == []
        assert result.json()["discoveryAvailable"] is False
        status = client.get("/api/availability").json()
        assert status["discoveryAvailable"] is False and status["savedFields"] == []
        # Scientific API callers still receive an explicit upstream error.
        assert client.get("/v1/search", params={"ra": 17, "dec": 6}).status_code == 502


def test_availability_exposes_saved_fields_and_recovers_after_a_probe(tmp_path):
    online = True
    calls = []

    def upstream(request):
        calls.append(request.url.path)
        return httpx.Response(200, content=sia_bytes()) if online else httpx.Response(502)

    settings = Settings(data_dir=tmp_path, retries=0)
    service = SkyService(settings, ArchiveClient(settings, httpx.MockTransport(upstream)))
    service.search(SearchRequest(ra=133.7, dec=-7.2, detectors=(6,)))
    online = False
    status = service.availability()
    assert status["discoveryAvailable"] is False
    assert len(status["savedFields"]) == 1
    assert status["savedFields"][0]["raDeg"] == 133.7
    assert status["savedFields"][0]["detectors"] == [6]
    assert service.availability() == status and len(calls) == 2
    online = True
    service._availability_until = 0
    assert service.availability()["discoveryAvailable"] is True
    assert service._search_unavailable_until == 0
