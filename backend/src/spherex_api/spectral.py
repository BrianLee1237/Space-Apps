"""Shared wavelength-grouping for SPHEREx's 102 nominal spectral channels.

SPHEREx's linear variable filter means the wavelength at a given sky
position differs between exposures of the same detector, and there is no
published per-pixel channel-boundary table to bin against. Instead, a
detector's real available exposures are sorted by their own recorded
bandpass and split into CHANNELS_PER_DETECTOR empirical groups. Sorting
uses each frame's detector_wavelength_min/max_um -- already returned by the
archive search itself, no FITS download needed -- so grouping a detector's
full exposure history costs nothing extra; only the frames actually chosen
for display or sampling get downloaded. Used by both channel mode
(/api/observations?mode=channel) and the spectral-fingerprint extraction
(/api/spectrum), the latter of which does this across all 6 detectors and
would otherwise need to download every exposure just to learn its
wavelength.
"""

# SPHEREx's mission documentation describes the full focal plane as 102
# nominal spectral channels; it divides evenly across the 6 detector arrays.
CHANNELS_PER_DETECTOR = 17


def split_evenly(items, groups):
    """Split a list into `groups` contiguous chunks of as-equal-as-possible size.

    With fewer items than groups, the first few groups get one item each and
    the rest are empty -- an honest reflection of limited archive coverage,
    not a reason to fabricate data to fill every slot.
    """
    count = len(items)
    base, extra = divmod(count, groups)
    result = []
    start = 0
    for index in range(groups):
        size = base + (1 if index < extra else 0)
        result.append(items[start : start + size])
        start += size
    return result


def wavelength_sorted_groups(frames, groups=CHANNELS_PER_DETECTOR):
    """Group one detector's real exposures into `groups` wavelength-sorted chunks.

    Returns (chunks, wavelength_min_um, wavelength_max_um). ``chunks`` is a
    list of ``groups`` frame lists (possibly empty). Sort key is the midpoint
    of each frame's own recorded detector_wavelength_min/max_um (from the
    archive search response); a frame missing that metadata is left out
    entirely rather than placed in an arbitrary slot.
    """
    dated = [
        (frame, (frame["detector_wavelength_min_um"] + frame["detector_wavelength_max_um"]) / 2)
        for frame in frames
        if frame.get("detector_wavelength_min_um") and frame.get("detector_wavelength_max_um")
    ]
    if not dated:
        return [[] for _ in range(groups)], None, None
    ordered = sorted(dated, key=lambda pair: pair[1])
    chunks = split_evenly([frame for frame, _ in ordered], groups)
    waves = [wave for _, wave in ordered]
    return chunks, min(waves), max(waves)
