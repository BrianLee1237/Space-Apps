import math
from typing import Annotated, Literal

import astropy.units as u
from astropy.coordinates import Angle
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Collection = Literal["spherex_dr1", "spherex_qr3", "spherex_dr1_deep", "spherex_qr3_deep"]


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    ra: float = Field(ge=0, lt=360, description="ICRS degrees, or sexagesimal hours")
    dec: float = Field(ge=-90, le=90, description="ICRS degrees, or sexagesimal degrees")
    fov_arcmin: float = Field(default=6, ge=0.5, le=60, description="Full square width")
    coverage: Literal["center", "field"] = Field(
        default="center",
        description="Search around the center or for any overlap with the full square field",
    )
    collections: tuple[Collection, ...] = Field(
        default=("spherex_dr1", "spherex_qr3"), min_length=1, max_length=4
    )
    detectors: tuple[Annotated[int, Field(ge=1, le=6)], ...] = Field(
        default=(1, 2, 3, 4, 5, 6), min_length=1, max_length=6
    )
    mjd_min: float | None = Field(default=None, ge=0)
    mjd_max: float | None = Field(default=None, ge=0)
    max_records: int = Field(default=10000, ge=1, le=20000)

    @field_validator("ra", "dec", mode="before", json_schema_input_type=float | str)
    @classmethod
    def coordinates(cls, value, info):
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                unit = u.hourangle if info.field_name == "ra" else u.deg
                try:
                    return float(Angle(value, unit=unit).degree)
                except (ValueError, u.UnitsError) as exc:
                    raise ValueError(
                        "Use decimal degrees or explicit sexagesimal coordinates"
                    ) from exc
        return value

    @model_validator(mode="after")
    def ordered(self):
        if self.mjd_min is not None and self.mjd_max is not None:
            if self.mjd_min > self.mjd_max:
                raise ValueError("mjd_min must not exceed mjd_max")
        self.collections = tuple(sorted(set(self.collections)))
        self.detectors = tuple(sorted(set(self.detectors)))
        return self

    @property
    def radius_deg(self):
        if self.coverage == "center":
            return 1 / 3600
        # Circumscribed circle, rather than the inscribed circle that misses corners.
        return self.fov_arcmin / 60 / math.sqrt(2)

    @property
    def cutout_size_deg(self):
        # IRSA cuts along detector axes. Pad for arbitrary detector rotation.
        return self.fov_arcmin / 60 * math.sqrt(2) + 2 * 6.2 / 3600
