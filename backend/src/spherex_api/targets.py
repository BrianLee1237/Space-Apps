"""Fixed, documented test fields. These are field centers, not predicted ephemerides."""

TARGETS = [
    {
        "id": "barnards-star",
        "name": "Barnard's Star",
        "ra": 269.4520769586187,
        "dec": 4.69336496657667,
        "fov_arcmin": 12,
        "coordinate_source": "CDS Sesame/SIMBAD J2000 ICRS position, retrieved 2026-11-14",
        "source_url": "https://simbad.cds.unistra.fr/simbad/sim-id?Ident=Barnard%27s+Star",
        "notes": (
            "High proper motion. The wide field uses a fixed catalog position "
            "without epoch propagation."
        ),
    },
    {
        "id": "epsilon-indi-b",
        "name": "Epsilon Indi B",
        "ra": 331.04414658852124,
        "dec": -56.78284419511611,
        "fov_arcmin": 8,
        "coordinate_source": "CDS Sesame/SIMBAD J2000 ICRS position, retrieved 2026-11-14",
        "source_url": "https://simbad.cds.unistra.fr/simbad/sim-id?Ident=eps+Ind+B",
        "notes": "Brown-dwarf pair B, not the primary star A. No promise of resolving the pair.",
    },
    {
        "id": "wise-0855",
        "name": "WISE 0855",
        "ra": 133.79512916666665,
        "dec": -7.245147222222222,
        "fov_arcmin": 10,
        "coordinate_source": (
            "Challenge coordinates 08h55m10.831s, -07d14m42.53s. Epoch unspecified."
        ),
        "source_url": None,
        "notes": "Very faint and fast-moving; coverage does not imply a detectable source.",
    },
    {
        "id": "rw-aurigae",
        "name": "RW Aurigae",
        "ra": 76.95652603458,
        "dec": 30.40143817389,
        "fov_arcmin": 6,
        "coordinate_source": "CDS Sesame/SIMBAD J2000 ICRS position, retrieved 2026-11-14",
        "source_url": "https://simbad.cds.unistra.fr/simbad/sim-id?Ident=RW+Aur",
        "notes": "Variability requires shared display limits and comparable spectral coverage.",
    },
    {
        "id": "r-draconis",
        "name": "R Draconis",
        "ra": 248.16761083295,
        "dec": 66.75497941722,
        "fov_arcmin": 6,
        "coordinate_source": "CDS Sesame/SIMBAD J2000 ICRS position, retrieved 2026-11-14",
        "source_url": "https://simbad.cds.unistra.fr/simbad/sim-id?Ident=R+Dra",
        "notes": "Inspect saturation/quality flags before measuring brightness changes.",
    },
]
