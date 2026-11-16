"""Rebuild the browser's 3I/ATLAS cutouts from the public IRSA release."""

import argparse
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.table import Table
from astropy.time import Time

from spherex_api.archive import ArchiveClient, cutout_url
from spherex_api.candidates import DEFAULT_CANDIDATE_REJECT_BITS
from spherex_api.config import Settings
from spherex_api.imaging import inspect_fits, output_wcs, registered_image
from spherex_api.models import SearchRequest

IRSA = "https://irsa.ipac.caltech.edu/data/SPHEREx/docs/comet3iatlas/"
OBSERVATIONS = (
    "2025W50_2A_0698_3D5",
    "2025W50_2A_0698_4D5",
    "2025W50_2A_0712_1D5",
    "2025W50_2A_0712_2D5",
)
PIXELS = 128
FOV = 9
PIXEL_UNIT = 0.0025
MASKED_PIXEL = -32768


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, help="Reuse downloaded IRSA tables and cutouts")
    inputs = parser.parse_args().inputs
    archive = ArchiveClient(Settings())
    with TemporaryDirectory() as folder:
        root = Path(folder)
        table = root / "comet.vot"
        if inputs:
            table = inputs / "comet.vot"
        else:
            table.write_bytes(archive.fetch(IRSA + "obscore_3I_Atlas.vot"))
        rows = {
            str(row["obs_creator_did"]): row
            for row in Table.read(table)
            if row["obs_creator_did"] in OBSERVATIONS
        }
        script = (
            (inputs / "comet-urls.txt").read_text() if inputs
            else archive.fetch(IRSA + "3IATLASImages-curl.sh").decode()
        )
        urls = re.findall(r"download_file '(https:[^']+\.fits)'", script)
        catalog = [rows[id_] for id_ in OBSERVATIONS]
        center = SearchRequest(
            ra=float(np.mean([row["comet_ra"] for row in catalog])),
            dec=float(np.mean([row["comet_dec"] for row in catalog])),
            fov_arcmin=FOV,
        )
        # A nearby patch from the same exposures, away from the published comet track.
        practice = center.model_copy(update={"dec": center.dec + 5 / 60, "fov_arcmin": 5})
        wcs = output_wcs(center, PIXELS)
        images = []
        backgrounds = []
        frames = []
        for id_, row in zip(OBSERVATIONS, catalog, strict=True):
            url = next(url for url in urls if id_ in url)
            target = SearchRequest(ra=row["comet_ra"], dec=row["comet_dec"], fov_arcmin=18)
            path = root / f"{id_}.fits"
            if inputs:
                path = inputs / "comet-fits" / f"{id_}.fits"
            else:
                path.write_bytes(archive.fetch(cutout_url(url, target)))
            metadata = inspect_fits(path, target)
            sky = SkyCoord(row["comet_ra"] * u.deg, row["comet_dec"] * u.deg)
            x, y = wcs.world_to_pixel(sky)
            frames.append({
                "id": id_,
                "time": Time(row["t_min"], format="mjd", scale="utc").isot + "Z",
                "wavelength": metadata["central_wavelength_um"],
                "sourceUrl": url,
                "position": [float(x), float(PIXELS - 1 - y)],
            })
            for request, planes in ((center, images), (practice, backgrounds)):
                plane = registered_image(path, request, PIXELS, DEFAULT_CANDIDATE_REJECT_BITS)
                if np.isfinite(plane).mean() < 0.8:
                    raise RuntimeError(f"Insufficient demo coverage in {id_}")
                planes.append(np.flipud(plane - np.nanmedian(plane)))

        output = Path(__file__).resolve().parents[2] / "frontend" / "public" / "motion-stack"
        output.mkdir(parents=True, exist_ok=True)
        (output / "comet.json").write_text(json.dumps({
            "size": PIXELS,
            "pixelUnit": PIXEL_UNIT,
            "arcsecPerPixel": FOV * 60 / PIXELS,
            "practiceArcsecPerPixel": practice.fov_arcmin * 60 / PIXELS,
            "frames": frames,
        }, indent=2) + "\n")
        pixels = np.stack(images + backgrounds)
        finite = np.isfinite(pixels)
        scaled = np.rint(pixels[finite] / PIXEL_UNIT)
        if np.any(np.abs(scaled) > 32767):
            raise RuntimeError("Demo brightness exceeds the signed 16-bit preview range")
        packed = np.full(pixels.shape, MASKED_PIXEL, dtype="<i2")
        packed[finite] = scaled
        (output / "comet.bin").write_bytes(packed.tobytes())


if __name__ == "__main__":
    main()
