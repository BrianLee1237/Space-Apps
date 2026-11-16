"""Offline regression tests for Gaia DR3 ESA/ARI failover and request caching."""

import httpx
import pytest

from spherex_api.archive import ArchiveError
from spherex_api.config import Settings
from spherex_api.gaia import GaiaClient

GAIA_JSON = {
    "metadata": [
        {"name": item}
        for item in (
            "source_id",
            "ra",
            "dec",
            "phot_g_mean_mag",
            "pmra",
            "pmdec",
            "parallax",
            "ref_epoch",
        )
    ],
    "data": [[1234567891234567890, 315.419398, 30.882677, 14.2, 1.0, -2.0, 5.0, 2016.0]],
}
GAIA_CSV = (
    "source_id,ra,dec,phot_g_mean_mag,pmra,pmdec,parallax,ref_epoch\n"
    "1234567891234567890,315.419398,30.882677,14.2,1.0,-2.0,5.0,2016.0\n"
    "2345678901234567890,315.420000,30.883000,16.3,,,,2016.0\n"
)


def test_gaia_primary_json_is_cached_without_contacting_mirror(tmp_path):
    requests = []

    def upstream(request):
        requests.append((request.url.host, str(request.content)))
        if request.url.host == "vizier.cfa.harvard.edu":
            return httpx.Response(503)
        assert request.url.host == "gea.esac.esa.int"
        return httpx.Response(200, json=GAIA_JSON)

    client = GaiaClient(Settings(data_dir=tmp_path), transport=httpx.MockTransport(upstream))
    cols, rows = client.cone_search(315.419398, 30.882677, 0.1, 75)
    assert cols[0] == "source_id" and rows[0][0] == 1234567891234567890
    assert client.cone_search(315.419398, 30.882677, 0.1, 75) == (cols, rows)
    assert len(requests) == 2


def test_gaia_esa_502_uses_real_ari_dr3_csv_then_caches(tmp_path):
    providers = []

    def upstream(request):
        providers.append(request.url.host)
        if request.url.host in {"gea.esac.esa.int", "vizier.cfa.harvard.edu"}:
            return httpx.Response(502, text="upstream down")
        assert request.url.host == "gaia.ari.uni-heidelberg.de"
        assert request.method == "GET"
        assert request.url.params["FORMAT"] == "CSV"
        assert "gaiadr3.gaia_source" in request.url.params["QUERY"]
        return httpx.Response(200, text=GAIA_CSV)

    client = GaiaClient(Settings(data_dir=tmp_path), transport=httpx.MockTransport(upstream))
    cols, rows = client.cone_search(315.419398, 30.882677, 0.1, 75)
    assert cols[:3] == ["source_id", "ra", "dec"]
    assert rows[0][0] == "1234567891234567890"  # Preserve 64-bit source ID exactly.
    assert rows[0][1] == pytest.approx(315.419398)
    assert rows[1][4] is None and rows[1][5] is None
    assert providers == ["vizier.cfa.harvard.edu", "gea.esac.esa.int", "gaia.ari.uni-heidelberg.de"]
    assert client.cone_search(315.419398, 30.882677, 0.1, 75) == (cols, rows)
    assert len(providers) == 3  # Same sky position/field reused from local cache.


def test_gaia_falls_back_when_esa_responds_with_invalid_json(tmp_path):
    def upstream(request):
        return (
            httpx.Response(200, text="broken")
            if request.url.host != "gaia.ari.uni-heidelberg.de"
            else httpx.Response(200, text=GAIA_CSV)
        )

    client = GaiaClient(Settings(data_dir=tmp_path), transport=httpx.MockTransport(upstream))
    assert len(client.cone_search(315, 31, 0.05, 20)[1]) == 2


def test_gaia_both_services_unavailable_is_honest_error(tmp_path):
    calls = []

    def upstream(request):
        calls.append(request.url.host)
        return httpx.Response(502, text="upstream unavailable")

    client = GaiaClient(Settings(data_dir=tmp_path), transport=httpx.MockTransport(upstream))
    with pytest.raises(ArchiveError, match="Harvard VizieR, ESA, and ARI"):
        client.cone_search(315, 31, 0.05, 20)
    assert calls == ["vizier.cfa.harvard.edu", "gea.esac.esa.int", "gaia.ari.uni-heidelberg.de"]
