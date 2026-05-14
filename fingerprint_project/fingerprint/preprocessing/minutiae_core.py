"""
Minutiae Extraction Core Pipeline
──────────────────────────────────
Ported from the working fingerprint-minutiae-extraction-main project.

Full pipeline:
  normalize → segment/ROI → orientation → frequency → gabor filter
  → skeletonize → crossing number (minutiae) → poincaré (singularities)

Each function mirrors the reference implementation exactly, adapted
for use as importable functions within the Django project.
"""

import math
import numpy as np
import cv2 as cv
import scipy.ndimage
from skimage.morphology import skeletonize as sk_skeletonize
import logging

logger = logging.getLogger('fingerprint')


# ════════════════════════════════════════════════
#  1. NORMALIZATION
# ════════════════════════════════════════════════

def _normalize_pixel(val, m, v, m0, v0):
    """Normalize a single pixel value."""
    x = np.sqrt((v0 * ((val - m) ** 2)) / v)
    if val < m:
        return m0 - x
    return m0 + x


def normalize(img, m0=100.0, v0=100.0):
    """
    Normalize image to reduce effects of sensor noise and
    finger pressure differences.

    Args:
        img: grayscale image (numpy array)
        m0: desired mean (default 100)
        v0: desired variance (default 100)

    Returns:
        Normalized image
    """
    m = np.mean(img)
    v = np.std(img) ** 2
    (w, h) = img.shape
    normalized = img.copy().astype(np.float64)
    for i in range(w):
        for j in range(h):
            normalized[i, j] = _normalize_pixel(img[i, j], m, v, m0, v0)
    return normalized.astype(np.uint8)


# ════════════════════════════════════════════════
#  2. SEGMENTATION (ROI + variance mask)
# ════════════════════════════════════════════════

def _normalise_for_seg(img):
    """Z-score normalization for segmentation."""
    std = np.std(img)
    if std < 1e-6:
        return img - np.mean(img)
    return (img - np.mean(img)) / std


def create_segmented_and_variance_images(im, w, threshold=0.2):
    """
    Segment the image into ROI by block-wise variance thresholding.

    Args:
        im: normalized grayscale image
        w: block size (e.g. 16)
        threshold: std threshold ratio

    Returns:
        (segmented_image, norm_img, mask)
    """
    (y, x) = im.shape
    threshold = np.std(im) * threshold

    image_variance = np.zeros(im.shape)
    segmented_image = im.copy()
    mask = np.ones_like(im, dtype=np.float64)

    for i in range(0, x, w):
        for j in range(0, y, w):
            box = [i, j, min(i + w, x), min(j + w, y)]
            block_stddev = np.std(im[box[1]:box[3], box[0]:box[2]])
            image_variance[box[1]:box[3], box[0]:box[2]] = block_stddev

    # Apply threshold
    mask[image_variance < threshold] = 0

    # Smooth mask with open/close morphological filter
    kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (w * 2, w * 2))
    mask_u8 = mask.astype(np.uint8)
    mask_u8 = cv.morphologyEx(mask_u8, cv.MORPH_OPEN, kernel)
    mask_u8 = cv.morphologyEx(mask_u8, cv.MORPH_CLOSE, kernel)
    mask = mask_u8.astype(np.float64)

    # Normalize segmented image
    segmented_image = segmented_image * mask
    im_norm = _normalise_for_seg(im.astype(np.float64))
    bg_pixels = im_norm[mask == 0]
    if len(bg_pixels) > 0 and np.std(bg_pixels) > 1e-6:
        mean_val = np.mean(bg_pixels)
        std_val = np.std(bg_pixels)
        norm_img = (im_norm - mean_val) / std_val
    else:
        norm_img = im_norm

    return segmented_image.astype(np.uint8), norm_img, mask


# ════════════════════════════════════════════════
#  3. ORIENTATION ESTIMATION
# ════════════════════════════════════════════════

def calculate_angles(im, W=16, smoth=False):
    """
    Calculate local ridge orientation in blocks.

    Args:
        im: grayscale image
        W: block width
        smoth: whether to smooth angles

    Returns:
        2D array of orientation angles (radians)
    """
    j1 = lambda x, y: 2 * x * y
    j2 = lambda x, y: x ** 2 - y ** 2

    (y, x) = im.shape

    sobel_op = [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]]
    ySobel = np.array(sobel_op).astype(np.int32)
    xSobel = np.transpose(ySobel).astype(np.int32)

    result = [[] for _ in range(1, y, W)]

    Gx_ = cv.filter2D(im / 125, -1, ySobel) * 125
    Gy_ = cv.filter2D(im / 125, -1, xSobel) * 125

    for j in range(1, y, W):
        for i in range(1, x, W):
            nominator = 0
            denominator = 0
            for l in range(j, min(j + W, y - 1)):
                for k in range(i, min(i + W, x - 1)):
                    Gx = round(Gx_[l, k])
                    Gy = round(Gy_[l, k])
                    nominator += j1(Gx, Gy)
                    denominator += j2(Gx, Gy)

            if nominator or denominator:
                angle = (math.pi + math.atan2(nominator, denominator)) / 2
                result[int((j - 1) // W)].append(angle)
            else:
                result[int((j - 1) // W)].append(0)

    result = np.array(result)

    if smoth:
        result = _smooth_angles(result)

    return result


def _gauss(x, y):
    ssigma = 1.0
    return (1 / (2 * math.pi * ssigma)) * math.exp(-(x * x + y * y) / (2 * ssigma))


def _kernel_from_function(size, f):
    kernel = [[] for _ in range(0, size)]
    for i in range(0, size):
        for j in range(0, size):
            kernel[i].append(f(i - size / 2, j - size / 2))
    return kernel


def _smooth_angles(angles):
    angles = np.array(angles)
    cos_angles = np.cos(angles.copy() * 2)
    sin_angles = np.sin(angles.copy() * 2)
    kernel = np.array(_kernel_from_function(5, _gauss))
    cos_angles = cv.filter2D(cos_angles / 125, -1, kernel) * 125
    sin_angles = cv.filter2D(sin_angles / 125, -1, kernel) * 125
    smooth = np.arctan2(sin_angles, cos_angles) / 2
    return smooth


def visualize_angles(im, mask, angles, W):
    """Visualize ridge orientations as line segments."""
    (y, x) = im.shape
    result = cv.cvtColor(np.zeros(im.shape, np.uint8), cv.COLOR_GRAY2RGB)
    mask_threshold = (W - 1) ** 2
    for i in range(1, x, W):
        for j in range(1, y, W):
            radian = np.sum(mask[j - 1:j + W, i - 1:i + W])
            if radian > mask_threshold:
                tang = math.tan(angles[(j - 1) // W][(i - 1) // W])
                (begin, end) = _get_line_ends(i, j, W, tang)
                cv.line(result, begin, end, color=150)
    cv.resize(result, im.shape, result)
    return result


def _get_line_ends(i, j, W, tang):
    if -1 <= tang <= 1:
        begin = (i, int((-W / 2) * tang + j + W / 2))
        end = (i + W, int((W / 2) * tang + j + W / 2))
    else:
        begin = (int(i + W / 2 + W / (2 * tang)), j + W // 2)
        end = (int(i + W / 2 - W / (2 * tang)), j - W // 2)
    return (begin, end)


# ════════════════════════════════════════════════
#  4. RIDGE FREQUENCY ESTIMATION
# ════════════════════════════════════════════════

def _frequest(im, orientim, kernel_size, minWaveLength, maxWaveLength):
    """Estimate ridge frequency within a small block."""
    rows, cols = np.shape(im)

    cosorient = np.cos(2 * orientim)
    sinorient = np.sin(2 * orientim)
    block_orient = math.atan2(sinorient, cosorient) / 2

    rotim = scipy.ndimage.rotate(
        im, block_orient / np.pi * 180 + 90,
        axes=(1, 0), reshape=False, order=3, mode="nearest",
    )

    cropsze = int(np.fix(rows / np.sqrt(2)))
    offset = int(np.fix((rows - cropsze) / 2))
    rotim = rotim[offset:offset + cropsze][:, offset:offset + cropsze]

    ridge_sum = np.sum(rotim, axis=0)
    dilation = scipy.ndimage.grey_dilation(
        ridge_sum, kernel_size, structure=np.ones(kernel_size)
    )
    ridge_noise = np.abs(dilation - ridge_sum)
    peak_thresh = 2
    maxpts = (ridge_noise < peak_thresh) & (ridge_sum > np.mean(ridge_sum))
    maxind = np.where(maxpts)
    _, no_of_peaks = np.shape(maxind)

    if no_of_peaks < 2:
        return np.zeros(im.shape)
    else:
        waveLength = (maxind[0][-1] - maxind[0][0]) / (no_of_peaks - 1)
        if minWaveLength <= waveLength <= maxWaveLength:
            return 1 / np.double(waveLength) * np.ones(im.shape)
        else:
            return np.zeros(im.shape)


def ridge_freq(im, mask, orient, block_size, kernel_size=5,
               minWaveLength=5, maxWaveLength=15):
    """Estimate ridge frequency across the entire image."""
    rows, cols = im.shape
    freq = np.zeros((rows, cols))

    for row in range(0, rows - block_size, block_size):
        for col in range(0, cols - block_size, block_size):
            image_block = im[row:row + block_size][:, col:col + block_size]
            angle_block = orient[row // block_size][col // block_size]
            if angle_block:
                freq[row:row + block_size][:, col:col + block_size] = _frequest(
                    image_block, angle_block, kernel_size,
                    minWaveLength, maxWaveLength
                )

    freq = freq * mask
    freq_1d = np.reshape(freq, (1, rows * cols))
    ind = np.where(freq_1d > 0)
    ind = np.array(ind)
    ind = ind[1, :]

    if len(ind) == 0:
        return np.zeros_like(mask)

    non_zero_elems = freq_1d[0][ind]
    medianfreq = np.median(non_zero_elems) * mask
    return medianfreq


# ════════════════════════════════════════════════
#  5. GABOR FILTERING
# ════════════════════════════════════════════════

def gabor_filter(im, orient, freq, kx=0.65, ky=0.65):
    """
    Apply oriented Gabor filter bank for ridge enhancement.

    Args:
        im: normalized image
        orient: orientation map
        freq: frequency map
        kx, ky: Gabor envelope parameters

    Returns:
        Enhanced binary ridge image (uint8)
    """
    angleInc = 3
    im = np.double(im)
    rows, cols = im.shape
    return_img = np.zeros((rows, cols))

    freq_1d = freq.flatten()
    frequency_ind = np.array(np.where(freq_1d > 0))
    non_zero_elems = freq_1d[frequency_ind]
    non_zero_elems = np.double(np.round((non_zero_elems * 100))) / 100
    unfreq = np.unique(non_zero_elems)

    if len(unfreq) == 0:
        return (255 * np.ones((rows, cols))).astype(np.uint8)

    sigma_x = 1 / unfreq * kx
    sigma_y = 1 / unfreq * ky
    block_size = int(np.round(3 * np.max([sigma_x, sigma_y])))
    array = np.linspace(-block_size, block_size, (2 * block_size + 1))
    x, y = np.meshgrid(array, array)

    reffilter = np.exp(
        -(
            (np.power(x, 2)) / (sigma_x * sigma_x)
            + (np.power(y, 2)) / (sigma_y * sigma_y)
        )
    ) * np.cos(2 * np.pi * unfreq[0] * x)

    filt_rows, filt_cols = reffilter.shape
    gabor_filters = np.array(np.zeros((180 // angleInc, filt_rows, filt_cols)))

    for degree in range(0, 180 // angleInc):
        rot_filt = scipy.ndimage.rotate(
            reffilter, -(degree * angleInc + 90), reshape=False
        )
        gabor_filters[degree] = rot_filt

    maxorientindex = np.round(180 / angleInc)
    orientindex = np.round(orient / np.pi * 180 / angleInc)

    for i in range(0, rows // 16):
        for j in range(0, cols // 16):
            if orientindex[i][j] < 1:
                orientindex[i][j] = orientindex[i][j] + maxorientindex
            if orientindex[i][j] > maxorientindex:
                orientindex[i][j] = orientindex[i][j] - maxorientindex

    block_size = int(block_size)
    valid_row, valid_col = np.where(freq > 0)
    finalind = np.where(
        (valid_row > block_size)
        & (valid_row < rows - block_size)
        & (valid_col > block_size)
        & (valid_col < cols - block_size)
    )

    for k in range(0, np.shape(finalind)[1]):
        r = valid_row[finalind[0][k]]
        c = valid_col[finalind[0][k]]
        img_block = im[r - block_size:r + block_size + 1][
            :, c - block_size:c + block_size + 1
        ]
        if img_block.shape == gabor_filters[0].shape:
            return_img[r][c] = np.sum(
                img_block * gabor_filters[int(orientindex[r // 16][c // 16]) - 1]
            )

    gabor_img = 255 - np.array((return_img < 0) * 255).astype(np.uint8)
    return gabor_img


# ════════════════════════════════════════════════
#  6. SKELETONIZATION
# ════════════════════════════════════════════════

def skeletonize(image_input):
    """
    Reduce binary ridge image to 1-pixel wide skeleton.

    Args:
        image_input: Gabor-filtered image (uint8, ridges dark)

    Returns:
        Skeletonized image (uint8, ridges dark on white)
    """
    image = np.zeros_like(image_input)
    image[image_input == 0] = 1.0
    output = np.zeros_like(image_input)
    skeleton = sk_skeletonize(image)
    output[skeleton] = 255
    cv.bitwise_not(output, output)
    return output


# ════════════════════════════════════════════════
#  7. CROSSING NUMBER (Minutiae Detection)
# ════════════════════════════════════════════════

def _minutiae_at(pixels, i, j, kernel_size=3):
    """
    Detect minutiae type at a single pixel using crossing number.

    Returns: 'ending', 'bifurcation', or 'none'
    """
    if pixels[i][j] == 1:
        if kernel_size == 3:
            cells = [
                (-1, -1), (-1, 0), (-1, 1), (0, 1),
                (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1),
            ]
        else:
            cells = [
                (-2, -2), (-2, -1), (-2, 0), (-2, 1), (-2, 2),
                (-1, 2), (0, 2), (1, 2), (2, 2), (2, 1),
                (2, 0), (2, -1), (2, -2), (1, -2), (0, -2),
                (-1, -2), (-2, -2),
            ]

        values = [pixels[i + l][j + k] for k, l in cells]

        crossings = 0
        for k in range(0, len(values) - 1):
            crossings += abs(values[k] - values[k + 1])
        crossings //= 2

        if crossings == 1:
            return "ending"
        if crossings == 3:
            return "bifurcation"

    return "none"


def calculate_minutiaes(im, kernel_size=3):
    """
    Detect all minutiae in a skeletonized image using crossing number.

    Args:
        im: skeletonized image (uint8)
        kernel_size: neighborhood size (3 or 5)

    Returns:
        (visualization_image, minutiae_list)
        minutiae_list: list of {"x": int, "y": int, "type": str}
    """
    binary_image = np.zeros_like(im)
    binary_image[im < 10] = 1.0
    binary_image = binary_image.astype(np.int8)

    (y, x) = im.shape
    result = cv.cvtColor(im, cv.COLOR_GRAY2RGB)
    colors = {"ending": (150, 0, 0), "bifurcation": (0, 150, 0)}

    minutiae_list = []

    for i in range(1, x - kernel_size // 2):
        for j in range(1, y - kernel_size // 2):
            minutiae = _minutiae_at(binary_image, j, i, kernel_size)
            if minutiae != "none":
                minutiae_list.append({"x": i, "y": j, "type": minutiae})
                cv.circle(result, (i, j), radius=2,
                          color=colors[minutiae], thickness=2)

    return result, minutiae_list


# ════════════════════════════════════════════════
#  8. POINCARÉ INDEX (Singularity Detection)
# ════════════════════════════════════════════════

def _poincare_index_at(i, j, angles, tolerance):
    """Compute Poincaré index at a single orientation block."""
    cells = [
        (-1, -1), (-1, 0), (-1, 1), (0, 1),
        (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1),
    ]

    angles_around = [math.degrees(angles[i - k][j - l]) for k, l in cells]
    index = 0
    for k in range(0, 8):
        difference = angles_around[k] - angles_around[k + 1]
        if difference > 90:
            difference -= 180
        elif difference < -90:
            difference += 180
        index += difference

    if 180 - tolerance <= index <= 180 + tolerance:
        return "loop"
    if -180 - tolerance <= index <= -180 + tolerance:
        return "delta"
    if 360 - tolerance <= index <= 360 + tolerance:
        return "whorl"
    return "none"


def calculate_singularities(im, angles, tolerance, W, mask):
    """
    Detect singularities (loop, delta, whorl) using Poincaré index.

    Args:
        im: skeletonized image
        angles: orientation map
        tolerance: angle tolerance in degrees
        W: block size
        mask: ROI mask

    Returns:
        (visualization_image, singularities_list)
    """
    result = cv.cvtColor(im, cv.COLOR_GRAY2RGB)
    colors = {"loop": (0, 0, 255), "delta": (0, 128, 255), "whorl": (255, 153, 255)}

    singularities_list = []

    for i in range(3, len(angles) - 2):
        for j in range(3, len(angles[i]) - 2):
            mask_slice = mask[(i - 2) * W:(i + 3) * W, (j - 2) * W:(j + 3) * W]
            mask_flag = np.sum(mask_slice)
            if mask_flag == (W * 5) ** 2:
                singularity = _poincare_index_at(i, j, angles, tolerance)
                if singularity != "none":
                    singularities_list.append(
                        {"x": j * W, "y": i * W, "type": singularity}
                    )
                    cv.rectangle(
                        result,
                        ((j + 0) * W, (i + 0) * W),
                        ((j + 1) * W, (i + 1) * W),
                        colors[singularity], 3,
                    )

    return result, singularities_list


# ════════════════════════════════════════════════
#  FULL PIPELINE ORCHESTRATOR
# ════════════════════════════════════════════════

def run_minutiae_pipeline(input_img, block_size=16):
    """
    Run the complete minutiae extraction pipeline on a grayscale image.

    Pipeline:
        1. Normalization
        2. Segmentation / ROI
        3. Orientation estimation
        4. Ridge frequency estimation
        5. Gabor filtering
        6. Skeletonization
        7. Minutiae detection (crossing number)
        8. Singularity detection (Poincaré index)

    Args:
        input_img: grayscale image (numpy uint8 array)
        block_size: processing block size (default 16)

    Returns:
        dict with keys:
            'normalized_img', 'segmented_img', 'mask',
            'orientation_img', 'angles', 'gabor_img',
            'thin_image', 'minutias_img', 'minutiae_points',
            'singularities_img', 'singularities_points'
    """
    logger.info("Minutiae pipeline: normalization...")
    normalized_img = normalize(input_img.copy(), float(100), float(100))

    logger.info("Minutiae pipeline: segmentation/ROI...")
    (segmented_img, normim, mask) = create_segmented_and_variance_images(
        normalized_img, block_size, 0.2
    )

    logger.info("Minutiae pipeline: orientation estimation...")
    angles = calculate_angles(normalized_img, W=block_size, smoth=False)
    orientation_img = visualize_angles(
        segmented_img, mask, angles, W=block_size
    )

    logger.info("Minutiae pipeline: ridge frequency estimation...")
    freq = ridge_freq(
        normim, mask, angles, block_size,
        kernel_size=5, minWaveLength=5, maxWaveLength=15,
    )

    logger.info("Minutiae pipeline: Gabor filtering...")
    gabor_img = gabor_filter(normim, angles, freq)

    logger.info("Minutiae pipeline: skeletonization...")
    thin_image = skeletonize(gabor_img)

    logger.info("Minutiae pipeline: minutiae detection (crossing number)...")
    minutias_img, minutiae_points = calculate_minutiaes(thin_image)

    logger.info("Minutiae pipeline: singularity detection (Poincaré)...")
    singularities_img, singularities_points = calculate_singularities(
        thin_image, angles, 1, block_size, mask
    )

    logger.info(
        "Minutiae pipeline complete: %d minutiae, %d singularities",
        len(minutiae_points), len(singularities_points)
    )

    return {
        'normalized_img': normalized_img,
        'segmented_img': segmented_img,
        'mask': mask,
        'angles': angles,
        'orientation_img': orientation_img,
        'gabor_img': gabor_img,
        'thin_image': thin_image,
        'minutias_img': minutias_img,
        'minutiae_points': minutiae_points,
        'singularities_img': singularities_img,
        'singularities_points': singularities_points,
    }
