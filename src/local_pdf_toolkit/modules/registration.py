"""根据建筑底图特征估算源页到目标页的显示坐标变换。"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

import cv2
import fitz
import numpy as np


class RegistrationError(RuntimeError):
    """底图配准失败或质量不满足阈值。"""


@dataclass(frozen=True)
class RegistrationSettings:
    render_scale: float = 0.35
    max_features: int = 40000
    contrast_threshold: float = 0.005
    edge_threshold: float = 20.0
    ratio_threshold: float = 0.90
    expected_scale: float = 1.0
    expected_x_ratio: float = 0.80
    expected_x_pixels: float | None = None
    expected_y_pixels: float = 12.0
    translation_tolerance_pixels: float = 24.0
    ransac_threshold_pixels: float = 1.5
    minimum_candidates: int = 20
    minimum_inliers: int = 15
    minimum_inlier_ratio: float = 0.20
    maximum_median_residual: float = 1.5
    minimum_scale: float = 0.98
    maximum_scale: float = 1.02
    maximum_rotation_degrees: float = 0.5

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "RegistrationSettings":
        known = {field.name for field in cls.__dataclass_fields__.values()}
        return cls(**{key: value for key, value in config.items() if key in known})


@dataclass(frozen=True)
class DisplayTransform:
    """源页显示坐标到目标页显示坐标的仿射变换。"""

    a: float
    b: float
    c: float
    d: float
    tx_pixels: float
    ty_pixels: float
    render_scale: float

    def map_display_point(self, point: fitz.Point) -> fitz.Point:
        tx = self.tx_pixels / self.render_scale
        ty = self.ty_pixels / self.render_scale
        return fitz.Point(
            self.a * point.x + self.b * point.y + tx,
            self.c * point.x + self.d * point.y + ty,
        )

    @property
    def linear_scale(self) -> float:
        return math.sqrt(abs(self.a * self.d - self.b * self.c))


@dataclass(frozen=True)
class RegistrationResult:
    transform: DisplayTransform
    source_keypoints: int
    target_keypoints: int
    candidate_matches: int
    inliers: int
    inlier_ratio: float
    median_residual_pixels: float
    p95_residual_pixels: float
    scale: float
    rotation_degrees: float

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["transform"] = asdict(self.transform)
        return result


def estimate_page_registration(
    source_page: fitz.Page,
    target_page: fitz.Page,
    settings: RegistrationSettings,
) -> RegistrationResult:
    """通过 SIFT 特征与 RANSAC 估算并验证相似变换。"""
    source_image = _render_gray(source_page, settings.render_scale)
    target_image = _render_gray(target_page, settings.render_scale)
    detector = cv2.SIFT_create(
        nfeatures=settings.max_features,
        contrastThreshold=settings.contrast_threshold,
        edgeThreshold=settings.edge_threshold,
    )
    source_keys, source_desc = detector.detectAndCompute(source_image, None)
    target_keys, target_desc = detector.detectAndCompute(target_image, None)
    if source_desc is None or target_desc is None:
        raise RegistrationError("页面没有足够的可配准特征")

    raw_matches = cv2.BFMatcher(cv2.NORM_L2).knnMatch(source_desc, target_desc, k=2)
    expected_x = settings.expected_x_pixels
    if expected_x is None:
        expected_x = (
            target_image.shape[1] - source_image.shape[1]
        ) * settings.expected_x_ratio
    candidates = []
    for nearest, second in raw_matches:
        if nearest.distance >= settings.ratio_threshold * second.distance:
            continue
        source_point = np.asarray(source_keys[nearest.queryIdx].pt)
        target_point = np.asarray(target_keys[nearest.trainIdx].pt)
        delta = target_point - settings.expected_scale * source_point
        if abs(float(delta[0]) - expected_x) > settings.translation_tolerance_pixels:
            continue
        if (
            abs(float(delta[1]) - settings.expected_y_pixels)
            > settings.translation_tolerance_pixels
        ):
            continue
        candidates.append(nearest)

    if len(candidates) < settings.minimum_candidates:
        raise RegistrationError(
            f"候选匹配不足: {len(candidates)} < {settings.minimum_candidates}"
        )

    source_points = np.float32(
        [source_keys[item.queryIdx].pt for item in candidates]
    ).reshape(-1, 1, 2)
    target_points = np.float32(
        [target_keys[item.trainIdx].pt for item in candidates]
    ).reshape(-1, 1, 2)
    matrix, mask = cv2.estimateAffinePartial2D(
        source_points,
        target_points,
        method=cv2.RANSAC,
        ransacReprojThreshold=settings.ransac_threshold_pixels,
        maxIters=50000,
        confidence=0.999,
        refineIters=50,
    )
    if matrix is None or mask is None:
        raise RegistrationError("RANSAC 未能得到有效变换")

    inlier_mask = mask.ravel().astype(bool)
    inliers = int(inlier_mask.sum())
    inlier_ratio = inliers / len(candidates)
    predicted = source_points[:, 0] @ matrix[:, :2].T + matrix[:, 2]
    residuals = np.linalg.norm(predicted - target_points[:, 0], axis=1)
    inlier_residuals = residuals[inlier_mask]
    median_residual = float(np.median(inlier_residuals))
    p95_residual = float(np.quantile(inlier_residuals, 0.95))
    scale = float(math.sqrt(abs(np.linalg.det(matrix[:, :2]))))
    rotation = float(math.degrees(math.atan2(matrix[1, 0], matrix[0, 0])))

    failures = []
    if inliers < settings.minimum_inliers:
        failures.append(f"内点 {inliers} < {settings.minimum_inliers}")
    if inlier_ratio < settings.minimum_inlier_ratio:
        failures.append(
            f"内点率 {inlier_ratio:.3f} < {settings.minimum_inlier_ratio:.3f}"
        )
    if median_residual > settings.maximum_median_residual:
        failures.append(
            f"中位残差 {median_residual:.3f}px > {settings.maximum_median_residual:.3f}px"
        )
    if not settings.minimum_scale <= scale <= settings.maximum_scale:
        failures.append(f"缩放 {scale:.6f} 超出允许范围")
    if abs(rotation) > settings.maximum_rotation_degrees:
        failures.append(f"旋转 {rotation:.4f}° 超出允许范围")
    if failures:
        raise RegistrationError("；".join(failures))

    return RegistrationResult(
        transform=DisplayTransform(
            a=float(matrix[0, 0]),
            b=float(matrix[0, 1]),
            c=float(matrix[1, 0]),
            d=float(matrix[1, 1]),
            tx_pixels=float(matrix[0, 2]),
            ty_pixels=float(matrix[1, 2]),
            render_scale=settings.render_scale,
        ),
        source_keypoints=len(source_keys),
        target_keypoints=len(target_keys),
        candidate_matches=len(candidates),
        inliers=inliers,
        inlier_ratio=inlier_ratio,
        median_residual_pixels=median_residual,
        p95_residual_pixels=p95_residual,
        scale=scale,
        rotation_degrees=rotation,
    )


def map_page_point(
    point: fitz.Point,
    source_page: fitz.Page,
    target_page: fitz.Page,
    transform: DisplayTransform,
) -> fitz.Point:
    """将 PyMuPDF 源页坐标映射到目标页坐标。"""
    source_display = fitz.Point(point) * source_page.rotation_matrix
    target_display = transform.map_display_point(source_display)
    return target_display * target_page.derotation_matrix


def map_page_rect(
    rect: fitz.Rect,
    source_page: fitz.Page,
    target_page: fitz.Page,
    transform: DisplayTransform,
) -> fitz.Rect:
    """映射矩形四角，并返回目标页中的外接矩形。"""
    points = [
        map_page_point(point, source_page, target_page, transform)
        for point in (rect.tl, rect.tr, rect.bl, rect.br)
    ]
    return fitz.Rect(
        min(point.x for point in points),
        min(point.y for point in points),
        max(point.x for point in points),
        max(point.y for point in points),
    )


def _render_gray(page: fitz.Page, scale: float) -> np.ndarray:
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(scale, scale),
        colorspace=fitz.csGRAY,
        alpha=False,
        annots=False,
    )
    return np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width
    )
