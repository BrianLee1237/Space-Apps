"""Bounded temporal sampling of real exposures for quick-look fingerprints."""


def split_evenly(items, groups):
    count = len(items)
    base, extra = divmod(count, groups)
    result = []
    start = 0
    for index in range(groups):
        size = base + (1 if index < extra else 0)
        result.append(items[start : start + size])
        start += size
    return result


def temporal_sample_groups(frames, groups=6):
    """Spread a bounded sample over observation dates. Wavelength comes from FITS."""
    return split_evenly(sorted(frames, key=lambda frame: frame["mjd_start"]), groups)
