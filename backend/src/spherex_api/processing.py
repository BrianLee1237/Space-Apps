"""Variance-aware registered coadds, differences, and motion-compensated stacks."""

import astropy.units as u
import numpy as np
from astropy.io import fits
from scipy.ndimage import convolve, maximum_filter, shift

from .imaging import asinh_unit_stretch, encode_rgba_png, output_wcs, spatial_wcs, spectral_wcs
from .photometry import REJECT_BITS


def bilinear_planes(image, variance, x, y):
    """Propagate independent input variances using squared interpolation weights."""
    finite = np.isfinite(x) & np.isfinite(y)
    safe_x, safe_y = np.where(finite, x, 0), np.where(finite, y, 0)
    ix, iy = np.floor(safe_x).astype(int), np.floor(safe_y).astype(int)
    fx, fy = safe_x - ix, safe_y - iy
    signal = np.zeros_like(safe_x)
    noise = np.zeros_like(safe_x)
    support = np.zeros_like(safe_x)
    for dx, dy, weight in (
        (0, 0, (1 - fx) * (1 - fy)),
        (1, 0, fx * (1 - fy)),
        (0, 1, (1 - fx) * fy),
        (1, 1, fx * fy),
    ):
        xx, yy = ix + dx, iy + dy
        inside = finite & (xx >= 0) & (xx < image.shape[1]) & (yy >= 0) & (yy < image.shape[0])
        xx, yy = np.clip(xx, 0, image.shape[1] - 1), np.clip(yy, 0, image.shape[0] - 1)
        values, errors = image[yy, xx], variance[yy, xx]
        valid = inside & np.isfinite(values) & np.isfinite(errors) & (errors > 0)
        signal += weight * np.where(valid, values, 0)
        noise += weight**2 * np.where(valid, errors, 0)
        support += weight * valid
    valid = support >= 1 - 1e-6
    return np.where(valid, signal, np.nan), np.where(valid, noise, np.nan)


def registered_planes(path, request, pixels=256, channel_bounds=None):
    with fits.open(path, memmap=False) as hdus:
        science = np.asarray(hdus["IMAGE"].data, dtype=float)
        variance = np.asarray(hdus["VARIANCE"].data, dtype=float)
        flags = np.asarray(hdus["FLAGS"].data, dtype=np.uint32)
        science = np.where((flags & REJECT_BITS) == 0, science, np.nan)
        if channel_bounds is not None:
            ny, nx = np.indices(science.shape)
            wave, _ = spectral_wcs(hdus).pixel_to_world(nx, ny)
            wavelengths = wave.to_value(u.um)
            science = np.where(
                (wavelengths >= channel_bounds[0]) & (wavelengths <= channel_bounds[1]),
                science,
                np.nan,
            )
        yy, xx = np.indices((pixels, pixels), dtype=float)
        world = output_wcs(request, pixels).pixel_to_world(xx, yy)
        x, y = spatial_wcs(hdus["IMAGE"].header).world_to_pixel(world)
        return bilinear_planes(science, variance, x, y)


def background_model(image, mode="constant"):
    valid = np.isfinite(image)
    if not valid.any() or mode == "none":
        return np.zeros_like(image), 0.0
    yy, xx = np.indices(image.shape, dtype=float)
    xx = (xx - image.shape[1] / 2) / image.shape[1]
    yy = (yy - image.shape[0] / 2) / image.shape[0]
    columns = [np.ones_like(image)] if mode == "constant" else [np.ones_like(image), xx, yy]
    design = np.stack([column[valid] for column in columns], axis=1)
    values = image[valid]
    # Bound the fit cost while retaining samples across the complete field.
    step = max(1, len(values) // 20000)
    design, values = design[::step], values[::step]
    keep = np.ones(len(values), dtype=bool)
    coefficients = np.zeros(len(columns))
    for _ in range(4):
        if np.count_nonzero(keep) < max(12, len(columns) * 3):
            break
        coefficients = np.linalg.lstsq(design[keep], values[keep], rcond=None)[0]
        residual = values - design @ coefficients
        scatter = 1.4826 * np.median(np.abs(residual[keep] - np.median(residual[keep])))
        if scatter <= 0:
            break
        keep = np.abs(residual) <= 3 * scatter
    model = sum(
        coefficient * column for coefficient, column in zip(coefficients, columns, strict=True)
    )
    residual = values[keep] - design[keep] @ coefficients
    if len(residual) > len(columns):
        covariance = np.linalg.pinv(design[keep].T @ design[keep]) * float(np.var(residual))
        grid = np.stack(columns, axis=-1)
        prediction_variance = np.einsum("...i,ij,...j->...", grid, covariance, grid)
    else:
        prediction_variance = np.zeros_like(image)
    return model, prediction_variance


def empirical_psf(image, radius=7):
    """Median normalized stamps from isolated, unsaturated bright image peaks."""
    valid = np.isfinite(image)
    values = image[valid]
    if len(values) < 100:
        return None, 0
    sky = np.median(values)
    noise = 1.4826 * np.median(np.abs(values - sky))
    signal = np.where(valid, image - sky, -np.inf)
    peaks = (signal == maximum_filter(signal, size=2 * radius + 1)) & (signal > max(8 * noise, 0))
    yy, xx = np.where(peaks)
    order = np.argsort(signal[yy, xx])[::-1]
    stamps, centers = [], []
    for index in order:
        x, y = xx[index], yy[index]
        if min(x, y) < radius or x + radius >= image.shape[1] or y + radius >= image.shape[0]:
            continue
        if any(np.hypot(x - a, y - b) < 3 * radius for a, b in centers):
            continue
        stamp = image[y - radius : y + radius + 1, x - radius : x + radius + 1] - sky
        if not np.isfinite(stamp).all():
            continue
        stamp = np.maximum(stamp, 0)
        total = stamp.sum()
        if total <= 0:
            continue
        sy, sx = np.indices(stamp.shape)
        dx, dy = (sx * stamp).sum() / total - radius, (sy * stamp).sum() / total - radius
        stamp = shift(stamp, (-dy, -dx), order=1, mode="constant", cval=0)
        stamps.append(stamp / stamp.sum())
        centers.append((x, y))
        if len(stamps) == 12:
            break
    if len(stamps) < 3:
        return None, len(stamps)
    result = np.median(stamps, axis=0)
    return result / result.sum(), len(stamps)


def convolve_planes(image, variance, kernel):
    valid = np.isfinite(image) & np.isfinite(variance)
    support = convolve(valid.astype(float), kernel, mode="constant", cval=0)
    signal = convolve(np.where(valid, image, 0), kernel, mode="constant", cval=0)
    noise = convolve(np.where(valid, variance, 0), kernel**2, mode="constant", cval=0)
    return (
        np.divide(signal, support, out=np.full_like(signal, np.nan), where=support >= 0.98),
        np.divide(noise, support**2, out=np.full_like(noise, np.nan), where=support >= 0.98),
    )


def reference_registration(earlier, later, excluded):
    """Robust relative offset from isolated reference peaks, excluding the target."""
    valid = np.isfinite(earlier)
    values = earlier[valid]
    if len(values) < 100:
        return {"dx": 0.0, "dy": 0.0, "stars": 0, "scatterPixels": None}
    sky = float(np.median(values))
    noise = 1.4826 * float(np.median(np.abs(values - sky)))
    score = np.where(valid, earlier - sky, -np.inf)
    peaks = (score == maximum_filter(score, size=15)) & (score > max(10 * noise, 0))
    yy, xx = np.where(peaks)
    offsets, centers = [], []
    for index in np.argsort(score[yy, xx])[::-1]:
        x, y = xx[index], yy[index]
        if min(x, y) < 8 or x + 8 >= earlier.shape[1] or y + 8 >= earlier.shape[0]:
            continue
        if excluded and np.hypot(x - excluded[0], y - excluded[1]) < 20:
            continue
        if any(np.hypot(x - a, y - b) < 15 for a, b in centers):
            continue
        local = later[y - 3 : y + 4, x - 3 : x + 4]
        if not np.isfinite(local).all():
            continue
        py, px = np.unravel_index(np.argmax(local), local.shape)
        if px in (0, 6) or py in (0, 6):
            continue
        coordinates = []
        for image, cx, cy in ((earlier, x, y), (later, x + px - 3, y + py - 3)):
            stamp = image[cy - 3 : cy + 4, cx - 3 : cx + 4]
            if not np.isfinite(stamp).all():
                break
            weights = np.maximum(stamp - np.median(stamp), 0)
            if weights.sum() <= 0:
                break
            sy, sx = np.indices(stamp.shape)
            coordinates.append(
                (
                    cx - 3 + np.sum(sx * weights) / weights.sum(),
                    cy - 3 + np.sum(sy * weights) / weights.sum(),
                )
            )
        if len(coordinates) == 2:
            offsets.append(np.subtract(coordinates[1], coordinates[0]))
            centers.append((x, y))
        if len(offsets) == 20:
            break
    if len(offsets) < 3:
        return {"dx": 0.0, "dy": 0.0, "stars": len(offsets), "scatterPixels": None}
    offsets = np.asarray(offsets)
    median = np.median(offsets, axis=0)
    distances = np.linalg.norm(offsets - median, axis=1)
    keep = distances <= max(0.5, 3 * 1.4826 * np.median(distances))
    if np.count_nonzero(keep) < 3 or np.linalg.norm(median) > 3:
        return {"dx": 0.0, "dy": 0.0, "stars": 0, "scatterPixels": None}
    median = np.median(offsets[keep], axis=0)
    return {
        "dx": float(median[0]),
        "dy": float(median[1]),
        "stars": int(np.count_nonzero(keep)),
        "scatterPixels": float(np.sqrt(np.mean((offsets[keep] - median) ** 2))),
    }


def robust_coadd(images, variances, sigma=5):
    stack, noise = np.stack(images), np.stack(variances)
    valid = np.isfinite(stack) & np.isfinite(noise) & (noise > 0)
    masked = np.ma.array(stack, mask=~valid)
    median = np.ma.median(masked, axis=0).filled(np.nan)
    scatter = 1.4826 * np.ma.median(np.ma.abs(masked - median), axis=0).filled(np.nan)
    threshold = sigma * np.sqrt(noise + np.where(np.isfinite(scatter), scatter**2, 0))
    # Two exposures cannot distinguish an outlier from real source variability.
    clipped = valid & (np.abs(stack - median) > threshold) & (valid.sum(axis=0) >= 3)
    valid &= ~clipped
    weight = np.divide(1, noise, out=np.zeros_like(noise), where=valid)
    total = weight.sum(axis=0)
    mean = np.divide(
        (np.where(valid, stack, 0) * weight).sum(axis=0),
        total,
        out=np.full_like(total, np.nan),
        where=total > 0,
    )
    variance = np.divide(1, total, out=np.full_like(total, np.nan), where=total > 0)
    counts = valid.sum(axis=0)
    enough = counts >= max(1, int(np.ceil(len(images) / 2)))
    return (
        np.where(enough, mean, np.nan),
        np.where(enough, variance, np.nan),
        counts,
        int(clipped.sum()),
    )


def render(image, difference=False):
    valid = np.isfinite(image)
    if not valid.any():
        raise ValueError("The selected observations have no usable overlapping pixels")
    if difference:
        scale = max(float(np.percentile(np.abs(image[valid]), 99)), 1e-12)
        value = asinh_unit_stretch(np.clip(np.nan_to_num(image) / scale, -1, 1))
        rgb = np.stack([np.maximum(value, 0), np.abs(value) * 0.25, np.maximum(-value, 0)], axis=-1)
    else:
        low, high = np.percentile(image[valid], [1, 99.5])
        value = asinh_unit_stretch(
            np.clip((np.nan_to_num(image, nan=low) - low) / max(high - low, 1e-12), 0, 1)
        )
        rgb = np.stack([value] * 3, axis=-1)
    rgba = np.concatenate(
        [np.round(rgb * 255).astype(np.uint8), (valid * 255).astype(np.uint8)[..., None]], axis=-1
    )
    return encode_rgba_png(rgba)


def process_stack(
    records,
    request,
    pixels=256,
    background="constant",
    rates=None,
    reference_mjd=None,
    progress=None,
    cancelled=None,
    channel_bounds=None,
):
    from astropy.time import Time

    images, variances = [], []
    scale = request.fov_arcmin * 60 / pixels
    for index, record in enumerate(records):
        if cancelled:
            cancelled()
        image, variance = registered_planes(record["path"], request, pixels, channel_bounds)
        model, sky_variance = background_model(image, background)
        image, variance = image - model, variance + sky_variance
        if rates:
            years = (Time(record["observedAt"]).mjd - reference_mjd) / 365.25
            dx, dy = rates[0] * years / scale, -rates[1] * years / scale
            yy, xx = np.indices(image.shape, dtype=float)
            image, variance = bilinear_planes(image, variance, xx - dx, yy - dy)
        images.append(image)
        variances.append(variance)
        if progress:
            progress(index + 1, len(records), "Registering and weighting exposures")
    image, variance, counts, rejected = robust_coadd(images, variances)
    return (
        image,
        variance,
        {
            "inputCount": len(records),
            "rejectedPixels": rejected,
            "medianCoverage": float(np.median(counts[counts > 0])) if np.any(counts > 0) else 0,
            "background": background,
            "pixelScaleArcsec": scale,
        },
    )


def process_difference(
    earlier, later, request, pixels=256, background="plane", target_pixel=None, channel_bounds=None
):
    a, va = registered_planes(earlier["path"], request, pixels, channel_bounds)
    b, vb = registered_planes(later["path"], request, pixels, channel_bounds)
    registration = reference_registration(a, b, target_pixel)
    if registration["stars"] >= 3:
        yy, xx = np.indices(a.shape, dtype=float)
        b, vb = bilinear_planes(b, vb, xx + registration["dx"], yy + registration["dy"])
    pa, na = empirical_psf(a)
    pb, nb = empirical_psf(b)
    matched = pa is not None and pb is not None
    if matched:
        # Cross-convolution gives both epochs the empirical PSF PA * PB.
        a, va = convolve_planes(a, va, pb)
        b, vb = convolve_planes(b, vb, pa)
    valid = np.isfinite(a) & np.isfinite(b) & np.isfinite(va) & np.isfinite(vb)
    photometric_scale = 1.0
    scale_variance = 0.0
    if np.count_nonzero(valid) > 100:
        bright = valid & (a > np.percentile(a[valid], 90))
        if target_pixel:
            yy, xx = np.indices(a.shape)
            bright &= np.hypot(xx - target_pixel[0], yy - target_pixel[1]) > 20
        av, bv = a[bright], b[bright]
        av, bv = av - np.median(av), bv - np.median(bv)
        retained = np.ones(len(av), dtype=bool)
        for _ in range(3):
            denominator = float(np.sum(av[retained] ** 2))
            if denominator <= 0:
                break
            proposed = float(np.sum(av[retained] * bv[retained]) / denominator)
            if not 0.5 <= proposed <= 2:
                break
            photometric_scale = proposed
            residual = bv - proposed * av
            sigma = 1.4826 * np.median(np.abs(residual - np.median(residual)))
            if sigma <= 0:
                break
            retained = np.abs(residual) <= 3 * sigma
        if np.count_nonzero(retained) > 2:
            denominator = float(np.sum(av[retained] ** 2))
            if denominator > 0:
                scale_variance = float(
                    np.sum((bv[retained] - photometric_scale * av[retained]) ** 2)
                )
                scale_variance /= (np.count_nonzero(retained) - 2) * denominator
    diff = b - photometric_scale * a
    model, sky_variance = background_model(diff, background)
    diff = np.where(valid, diff - model, np.nan)
    variance = np.where(
        valid, vb + photometric_scale**2 * va + a**2 * scale_variance + sky_variance, np.nan
    )
    significance = np.divide(
        diff, np.sqrt(variance), out=np.full_like(diff, np.nan), where=variance > 0
    )
    return (
        diff,
        significance,
        {
            "empiricalPsfMatched": matched,
            "referenceRegistration": registration,
            "psfStars": [na, nb],
            "photometricScale": photometric_scale,
            "background": background,
            "variancePropagated": True,
            "warnings": [
                "Statistical significance excludes correlated interpolation "
                "and calibration systematics.",
                "Empirical cross-convolution broadens both epochs "
                "and requires isolated reference stars."
                if matched
                else "Too few isolated reference stars for empirical PSF matching.",
                "Photometric scaling assumes a predominantly stable reference population.",
            ],
        },
    )
