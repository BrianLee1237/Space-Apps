"""Explicit opt-in integration check against IRSA; never run by the unit tests.

Run: uv run python scripts/validate_live.py --frames-per-target 2
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from spherex_api.app import app
from spherex_api.targets import TARGETS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames-per-target", type=int, choices=[0, 1, 2], default=1)
    parser.add_argument("--target", choices=[t["id"] for t in TARGETS])
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--output", default="data/reports/live-validation.json")
    args = parser.parse_args()
    report = {"checked_at_utc": datetime.now(UTC).isoformat(), "targets": []}
    with TestClient(app) as client:
        for target in TARGETS:
            if args.target and args.target != target["id"]:
                continue
            entry = {"target": target, "samples": []}
            print(f"Searching {target['name']}...", flush=True)
            try:
                response = client.post(
                    "/v1/search",
                    params={"refresh": args.refresh},
                    json={
                        "ra": target["ra"],
                        "dec": target["dec"],
                        "fov_arcmin": target["fov_arcmin"],
                    },
                )
                response.raise_for_status()
                manifest = response.json()
                entry.update(
                    {
                        key: manifest[key]
                        for key in [
                            "search_id",
                            "created_at_utc",
                            "complete",
                            "frame_count",
                            "archive_rows_returned",
                            "mjd_min",
                            "mjd_max",
                        ]
                    }
                )
                entry["detector_counts"] = {
                    str(d): sum(f["detector"] == d for f in manifest["frames"]) for d in range(1, 7)
                }
                candidates = [f for f in manifest["frames"] if f["detector"] == 6]
                if not candidates:
                    candidates = manifest["frames"]
                selected = []
                if candidates and args.frames_per_target:
                    selected.append(candidates[0])
                if len(candidates) > 1 and args.frames_per_target == 2:
                    selected.append(candidates[-1])
                for frame in selected:
                    sample = {"frame_id": frame["frame_id"], "mjd_start": frame["mjd_start"]}
                    entry["samples"].append(sample)
                    try:
                        response = client.get(frame["links"]["metadata"])
                        response.raise_for_status()
                        metadata = response.json()
                        sample.update(
                            {
                                key: metadata[key]
                                for key in [
                                    "cutout_url",
                                    "shape_yx",
                                    "central_wavelength_um",
                                    "central_bandwidth_um",
                                    "nonzero_flag_fraction",
                                    "center_flags",
                                    "center_flag_names",
                                    "sha256",
                                    "bytes",
                                    "processing_version",
                                    "requested_center_inside_image",
                                ]
                            }
                        )
                        response = client.get(frame["links"]["fits"])
                        response.raise_for_status()
                        sample["fits_download_status"] = response.status_code
                        response = client.get(frame["links"]["preview"], params={"pixels": 256})
                        response.raise_for_status()
                        sample["preview_status"] = response.status_code
                        sample["preview_valid_fraction"] = float(
                            response.headers["x-preview-valid-fraction"]
                        )
                        image_path = (
                            Path(args.output).parent / f"{target['id']}-{frame['frame_id']}.png"
                        )
                        image_path.parent.mkdir(parents=True, exist_ok=True)
                        image_path.write_bytes(response.content)
                        sample["preview_file"] = str(image_path)
                    except Exception as exc:
                        sample["error"] = str(exc)
                        if isinstance(exc, httpx.HTTPStatusError):
                            sample["error_detail"] = exc.response.text[:1000]
                entry["status"] = (
                    "pass"
                    if entry["complete"]
                    and entry["frame_count"]
                    and all("error" not in s for s in entry["samples"])
                    else "incomplete"
                )
                print(
                    f"{target['name']}: {entry['frame_count']} frames; "
                    f"complete={entry['complete']}; status={entry['status']}",
                    flush=True,
                )
            except Exception as exc:
                entry.update({"status": "failed", "error": str(exc)})
                print(f"{target['name']}: FAILED {exc}", flush=True)
            report["targets"].append(entry)
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    raise SystemExit(0 if all(t["status"] == "pass" for t in report["targets"]) else 1)


if __name__ == "__main__":
    main()
