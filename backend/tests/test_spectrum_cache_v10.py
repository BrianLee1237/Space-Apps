"""Regression checks: cached spectral measurements never require a new IRSA search."""

from pathlib import Path

import pytest

from spherex_api import spectrum
from spherex_api.archive import ArchiveError


class FakeStore:
    def __init__(self, root: Path):
        self.root = root

    def path(self, kind, frame_id, suffix):
        assert kind == "cutouts"
        return self.root / f"{frame_id}{suffix}"


class OfflineSky:
    def __init__(self, root):
        self.store = FakeStore(root)
        self.search_calls = 0

    def search(self, query):
        self.search_calls += 1
        raise ArchiveError("IRSA returned HTTP 502")


def manifest_for(count):
    return {
        "frames": [
            {"frame_id": f"{i:024x}", "observed_at_utc": f"2025-05-{i + 1:02d}T00:00:00Z"}
            for i in range(count)
        ]
    }


def test_cached_exposures_produce_real_partial_fingerprint_without_irsa(monkeypatch, tmp_path):
    manifest = manifest_for(3)
    sky = OfflineSky(tmp_path)
    for f in manifest["frames"]:
        sky.store.path("cutouts", f["frame_id"], ".fits").write_bytes(b"cached-fits")

    seen = []

    def measured_fits(path, ra, dec):
        assert (ra, dec) == (315.419398, 30.882677)
        seen.append(path)
        n = int(path.stem, 16)
        return {
            "wavelengthMicron": 4.8 + n * 0.1,
            "flux": 2.0 + n,
            "uncertainty": 0.2,
            "qualityFlags": [],
            "bunit": "MJy/sr",
        }

    monkeypatch.setattr(spectrum, "point_sample", measured_fits)
    samples, warnings = spectrum.build_fingerprint(
        sky, 315.419398, 30.882677, 10, existing_manifest=manifest
    )
    assert sky.search_calls == 0
    assert len(samples) == len(seen) == 3
    assert [v["wavelengthMicron"] for v in samples] == pytest.approx([4.8, 4.9, 5.0])
    assert all(v["observedAt"] for v in samples)
    assert any("partial" in text.lower() and "cached" in text.lower() for text in warnings)


def test_no_cache_explains_offline_irsa_without_fake_spectrum(tmp_path):
    sky = OfflineSky(tmp_path)
    samples, warnings = spectrum.build_fingerprint(
        sky, 315.4, 30.8, 10, existing_manifest=manifest_for(2)
    )
    assert sky.search_calls == 0
    assert samples == []
    assert any("No valid cached pixels" in text for text in warnings)


def test_rejected_pixels_remain_rejected(monkeypatch, tmp_path):
    sky = OfflineSky(tmp_path)
    manifest = manifest_for(2)
    for frame in manifest["frames"]:
        sky.store.path("cutouts", frame["frame_id"], ".fits").write_bytes(b"cached")
    monkeypatch.setattr(spectrum, "point_sample", lambda *args: None)
    samples, warnings = spectrum.build_fingerprint(sky, 315.4, 30.8, 10, existing_manifest=manifest)
    assert samples == []
    assert sky.search_calls == 0
    assert any("No valid cached pixels" in text for text in warnings)
