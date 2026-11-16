import io
import threading
import time

import httpx
import numpy as np
import pytest
from astropy.io import fits
from astropy.time import Time
from fastapi.testclient import TestClient
from test_science_and_api import DATA_URL, mef_bytes, sia_bytes

from spherex_api.analysis import fit_motion
from spherex_api.app import create_app
from spherex_api.archive import ArchiveClient, CapacityError
from spherex_api.config import Settings
from spherex_api.jobs import JobManager
from spherex_api.models import SearchRequest
from spherex_api.photometry import aperture_measurement, wavelength_time_cells
from spherex_api.processing import bilinear_planes, empirical_psf, robust_coadd
from spherex_api.reviews import ReviewStore
from spherex_api.service import SkyService
from spherex_api.storage import Store


def wait_for_job(client, submitted):
    key = submitted.json()["id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        job = client.get(f"/api/science/jobs/{key}").json()
        if job["state"] in {"complete", "failed", "cancelled"}:
            return job
        time.sleep(0.02)
    pytest.fail("Analysis job did not finish")


def test_aperture_flux_scales_and_informational_flags_survive(tmp_path):
    query = SearchRequest(ra=133.7, dec=-7.2, fov_arcmin=10)
    paths = []
    for index, amplitude in enumerate((1, 2)):
        with fits.open(io.BytesIO(mef_bytes(query))) as hdus:
            hdus["IMAGE"].data *= amplitude
            hdus["FLAGS"].data[38, 40] = 1 << 21
            hdus["FLAGS"].header["MSKN0021"] = "SOURCE"
            path = tmp_path / f"image-{index}.fits"
            hdus.writeto(path)
            paths.append(path)
    from spherex_api.imaging import output_wcs

    position = output_wcs(query, 64).pixel_to_world(40, 38)
    a = aperture_measurement(paths[0], position.ra.deg, position.dec.deg, 20)
    b = aperture_measurement(paths[1], position.ra.deg, position.dec.deg, 20)
    assert a and b
    assert a["flux"] > 0 and a["uncertainty"] > 0
    assert b["flux"] == pytest.approx(2 * a["flux"])
    assert "SOURCE" in a["qualityFlags"]
    assert a["channel"] == 88


def test_bilinear_variance_uses_squared_weights():
    image = np.array([[1.0, 2.0], [3.0, 4.0]])
    result, variance = bilinear_planes(
        image, np.full((2, 2), 4.0), np.array([[0.5]]), np.array([[0.5]])
    )
    assert result[0, 0] == pytest.approx(2.5)
    assert variance[0, 0] == pytest.approx(1)
    image[0, 0] = np.nan
    assert np.isnan(
        bilinear_planes(image, np.ones((2, 2)), np.array([[0.5]]), np.array([[0.5]]))[0]
    ).all()


def test_atlas_maps_nonuniform_cube_layers_to_exact_tiles():
    from fastapi import FastAPI

    from spherex_api.atlas import atlas_router

    class Archive:
        def fetch(self, url):
            return b"hips_order = 5\nhips_cube_depth = 102\nhips_pixel_cut = 0 40\n"

    app = FastAPI()
    app.include_router(atlas_router(Archive()), prefix="/atlas")
    with TestClient(app) as client:
        response = client.get("/atlas/100/properties")
        assert "dataproduct_type = image" in response.text
        assert "hips_cube_depth" not in response.text
        assert "hips_pixel_cut" not in response.text
        for channel, filename in ((1, "Npix0.png"), (100, "Npix0_99.png")):
            response = client.get(
                f"/atlas/{channel}/Norder0/Dir0/Npix0.png", follow_redirects=False
            )
            assert response.status_code == 307
            assert response.headers["location"].endswith(filename)
        assert client.get("/atlas/103/properties").status_code == 422
        assert client.get("/atlas/1/Norder0/Dir0/Npix12.png").status_code == 404


def test_aperture_sky_reaches_beyond_known_source_mask(tmp_path):
    from spherex_api.imaging import output_wcs

    query = SearchRequest(ra=133.7, dec=-7.2, fov_arcmin=10)
    path = tmp_path / "extended-source-mask.fits"
    with fits.open(io.BytesIO(mef_bytes(query))) as hdus:
        yy, xx = np.indices(hdus["FLAGS"].data.shape)
        hdus["FLAGS"].data[np.hypot(xx - 40, yy - 38) <= 6] = 1 << 21
        hdus.writeto(path)
    position = output_wcs(query, 64).pixel_to_world(40, 38)
    measured = aperture_measurement(path, position.ra.deg, position.dec.deg, 20)
    assert measured is not None
    assert measured["flux"] > 0


def test_variance_weighting_and_cosmic_ray_rejection():
    images = [np.ones((3, 3)), np.ones((3, 3)), np.full((3, 3), 100.0)]
    output, variance, count, rejected = robust_coadd(images, [np.ones((3, 3))] * 3)
    assert output[1, 1] == pytest.approx(1)
    assert variance[1, 1] == pytest.approx(0.5)
    assert count[1, 1] == 2
    assert rejected == 9


def test_motion_compensated_stack_aligns_injected_source(monkeypatch):
    from spherex_api import processing

    yy, xx = np.indices((32, 32))
    images = [20 * np.exp(-((xx - x) ** 2 + (yy - 16) ** 2) / 2) for x in (16, 12)]
    monkeypatch.setattr(
        processing, "registered_planes", lambda path, *args: (images[path], np.ones((32, 32)))
    )
    first = Time("2020-01-01").mjd
    records = [
        {"path": i, "observedAt": Time(first + i * 365.25, format="mjd").isot} for i in range(2)
    ]
    query = SearchRequest(ra=10, dec=0, fov_arcmin=1)
    stationary, _, _ = processing.process_stack(records, query, pixels=32, background="none")
    moving, _, _ = processing.process_stack(
        records, query, pixels=32, background="none", rates=(7.5, 0), reference_mjd=first
    )
    assert moving[16, 16] > 1.9 * stationary[16, 16]


def test_reference_registration_recovers_common_image_offset():
    from scipy.ndimage import shift

    from spherex_api.processing import reference_registration

    yy, xx = np.indices((128, 128))
    image = np.zeros((128, 128))
    for x, y in ((25, 25), (75, 25), (25, 75), (90, 90)):
        image += 10 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / 4)
    later = shift(image, (0.6, 1.2), order=1)
    fitted = reference_registration(image, later, (64, 64))
    assert fitted["stars"] >= 3
    assert fitted["dx"] == pytest.approx(1.2, abs=0.2)
    assert fitted["dy"] == pytest.approx(0.6, abs=0.2)


def test_weighted_motion_model_and_epoch_cells():
    first = Time("2020-01-01").mjd
    positions = [
        {
            "raDeg": 10 + 10 * year / 3600,
            "decDeg": -5 * year / 3600,
            "observedAt": Time(first + 365.25 * year, format="mjd").isot,
            "uncertaintyArcsec": 0.5,
        }
        for year in range(3)
    ]
    result = fit_motion(positions)
    assert result["eastArcsecPerYear"] == pytest.approx(10, abs=0.01)
    assert result["northArcsecPerYear"] == pytest.approx(-5, abs=0.01)
    assert result["rateUncertaintyArcsecPerYear"] > 0
    points = [
        {"observedAt": "2020-01-01", "channel": 88, "flux": flux, "uncertainty": 1}
        for flux in (10, 30)
    ]
    cells = wavelength_time_cells(points)
    assert cells[0]["flux"] == 20
    assert cells[0]["uncertainty"] >= 10


def test_empirical_psf_requires_independent_stamps():
    y, x = np.indices((128, 128))
    image = np.random.default_rng(42).normal(0, 0.01, (128, 128))
    for cx, cy in ((25, 25), (75, 25), (25, 75), (90, 90)):
        image += 10 * np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / 4)
    psf, count = empirical_psf(image)
    assert psf is not None and count >= 3
    assert psf.sum() == pytest.approx(1)


def test_jobs_deduplicate_and_cancel_only_last_subscriber():
    manager = JobManager(workers=1)
    release = threading.Event()

    def work(progress, cancelled):
        release.wait(2)
        cancelled()
        return {"value": 42}

    try:
        first, a = manager.submit("example", {}, work)
        second, b = manager.submit("example", {}, work)
        assert first["id"] == second["id"]
        manager.release(first["id"], a)
        assert not manager.jobs[first["id"]].cancel.is_set()
        release.set()
        deadline = time.monotonic() + 3
        while manager.snapshot(first["id"])["state"] != "complete" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert manager.snapshot(first["id"])["result"] == {"value": 42}
        manager.release(first["id"], b)
    finally:
        release.set()
        manager.close()


def test_cache_eviction_protects_active_jobs_and_evidence(tmp_path):
    old = tmp_path / "cutouts" / ("a" * 24 + ".fits")
    old.parent.mkdir()
    old.write_bytes(b"x" * 40)
    import os

    os.utime(old, (0, 0))
    evidence = tmp_path / "evidence.sqlite3"
    evidence.write_bytes(b"x" * 10)
    store = Store(Settings(data_dir=tmp_path, cache_budget_bytes=100))
    new = store.path("previews", "b" * 24, ".png")
    with store.pin(["c" * 24 + "." + "a" * 24]):
        with pytest.raises(CapacityError):
            store.write_bytes(new, b"n" * 80)
    assert old.exists()
    store.write_bytes(new, b"n" * 80)
    assert not old.exists() and evidence.exists() and new.exists()


def test_reviews_persist_and_one_reviewer_updates_one_assessment(tmp_path):
    store = ReviewStore(tmp_path)
    key = store.submit({"note": "Real evidence references", "analysis": {"version": 2}})
    store.assess(key, "browser-one", "artifact", "edge")
    store.assess(key, "browser-one", "uncertain", "needs review")
    assert ReviewStore(tmp_path).list()[0]["assessments"] == {"uncertain": 1}
    assert store.get(key)["assessments"] == {"uncertain": 1}


def test_science_jobs_inspect_all_epochs_and_return_provenance(tmp_path):
    query = SearchRequest(ra=133.7, dec=-7.2, fov_arcmin=10)
    rows = [
        (
            DATA_URL.replace("example", f"example-{i}"),
            f"observation-{i}",
            "SPHEREx-D6",
            "spherex_dr1",
            60900 + day,
        )
        for i, day in enumerate((0, 1, 30, 31))
    ]

    def upstream(request):
        if request.url.path == "/SIA":
            return httpx.Response(200, content=sia_bytes(rows=rows))
        return httpx.Response(200, content=mef_bytes(query))

    settings = Settings(data_dir=tmp_path)
    service = SkyService(settings, ArchiveClient(settings, httpx.MockTransport(upstream)))
    with TestClient(create_app(settings, service=service)) as client:
        frames = client.get("/api/observations", params={"ra": query.ra, "dec": query.dec}).json()[
            "observations"
        ]
        submitted = client.post(
            "/api/science/jobs", json={"kind": "matches", "ids": [row["id"] for row in frames]}
        )
        assert submitted.status_code == 200
        job = wait_for_job(client, submitted)
        assert job["state"] == "complete", job
        assert job["result"]["inspected"] == 4
        assert len(job["result"]["provenance"]["observations"]) == 4
        assert len(job["result"]["provenance"]["codeSha256"]) == 64
        assert "astropy" in job["result"]["provenance"]["libraries"]
        assert (
            client.post("/api/science/evidence", json={"record": {"analysis": {}}}).status_code
            == 422
        )
        measured = client.post(
            "/api/science/jobs",
            json={
                "kind": "photometry",
                "ids": [row["id"] for row in frames],
                "referenceId": frames[0]["id"],
                "x": 319.5 / 511,
                "y": 1 - 307.5 / 511,
                "radiusArcsec": 20,
            },
        )
        photometry = wait_for_job(client, measured)
        assert photometry["state"] == "complete", photometry
        assert len(photometry["result"]["samples"]) == 4
        assert all(point["uncertainty"] > 0 for point in photometry["result"]["samples"])
        evidence = client.post(
            "/api/science/evidence",
            json={"record": {"analysis": photometry["result"], "note": "Regression evidence"}},
        )
        assert evidence.status_code == 200, evidence.text
        assert client.get("/api/science/evidence/" + evidence.json()["id"]).status_code == 200
        assert (
            client.post(
                "/api/science/jobs", json={"kind": "matches", "ids": ["invalid"]}
            ).status_code
            == 422
        )


def test_bounded_job_keeps_the_selected_reference(tmp_path, monkeypatch):
    from spherex_api import science

    query = SearchRequest(ra=133.7, dec=-7.2, fov_arcmin=10)
    rows = [
        (
            DATA_URL.replace("example", f"example-{i}"),
            str(i),
            "SPHEREx-D6",
            "spherex_dr1",
            60900 + i,
        )
        for i in range(300)
    ]

    def upstream(request):
        content = sia_bytes(rows=rows) if request.url.path == "/SIA" else mef_bytes(query)
        return httpx.Response(200, content=content)

    settings = Settings(data_dir=tmp_path)
    service = SkyService(settings, ArchiveClient(settings, httpx.MockTransport(upstream)))
    with TestClient(create_app(settings, service=service)) as client:
        frames = client.get("/api/observations", params={"ra": query.ra, "dec": query.dec}).json()[
            "observations"
        ]
        ids = [row["id"] for row in frames]
        selected = {round(i * 299 / 255) for i in range(256)}
        reference = ids[next(i for i in range(300) if i not in selected)]
        monkeypatch.setattr(
            service, "frame", lambda *args: (tmp_path / "unused.fits", {"detector": 6})
        )
        monkeypatch.setattr(science, "matched_pairs", lambda *args, **kwargs: [])
        monkeypatch.setattr(science, "point_sample", lambda *args: {"wavelengthMicron": 4.5})
        response = client.post(
            "/api/science/jobs", json={"kind": "matches", "ids": ids, "referenceId": reference}
        )
        job = wait_for_job(client, response)
        assert job["state"] == "complete", job
        observations = job["result"]["provenance"]["observations"]
        assert len(observations) == 256
        assert reference in {row["id"] for row in observations}
