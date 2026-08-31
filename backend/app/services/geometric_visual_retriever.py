from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np
from PIL import Image, ImageOps

from app.domain.source_assets import OriginalAssetData


DEFAULT_CANDIDATE_MAX_EDGE = 1600
DEFAULT_SIFT_NFEATURES = 10_000


@dataclass(frozen=True, slots=True)
class GeometricVisualEvidence:
    source_asset_id: str
    score: float
    good_matches: int
    inliers: int
    inlier_ratio: float


class GeometricVisualRetriever:
    """Verify panel/source identity using local visual features only.

    The retriever deliberately ignores filenames, paths, captions and sequence
    metadata. SIFT descriptor correspondences are filtered with Lowe's ratio
    test and then verified by a RANSAC homography so crop/resize/rotation can be
    recovered without lowering the Tier-0 pixel threshold.

    Panel features keep their original resolution and unbounded SIFT behavior.
    Candidate JPGs are bounded before SIFT extraction so very large originals
    cannot dominate both feature extraction and brute-force descriptor matching.
    """

    def __init__(
        self,
        *,
        lowe_ratio: float = 0.75,
        minimum_inliers: int = 12,
        minimum_inlier_ratio: float = 0.55,
        ransac_reprojection_threshold: float = 5.0,
        candidate_max_edge: int = DEFAULT_CANDIDATE_MAX_EDGE,
        sift_nfeatures: int = DEFAULT_SIFT_NFEATURES,
    ) -> None:
        if not 0.0 < lowe_ratio < 1.0:
            raise ValueError("lowe_ratio must be between 0 and 1")
        if minimum_inliers < 4:
            raise ValueError("minimum_inliers must be at least 4")
        if not 0.0 <= minimum_inlier_ratio <= 1.0:
            raise ValueError("minimum_inlier_ratio must be between 0 and 1")
        if ransac_reprojection_threshold <= 0.0:
            raise ValueError("ransac_reprojection_threshold must be positive")
        if candidate_max_edge < 1:
            raise ValueError("candidate_max_edge must be positive")
        if sift_nfeatures < 1:
            raise ValueError("sift_nfeatures must be positive")

        self._lowe_ratio = float(lowe_ratio)
        self._minimum_inliers = int(minimum_inliers)
        self._minimum_inlier_ratio = float(minimum_inlier_ratio)
        self._ransac_reprojection_threshold = float(ransac_reprojection_threshold)
        self._candidate_max_edge = int(candidate_max_edge)
        self._sift_nfeatures = int(sift_nfeatures)
        self._sift = cv2.SIFT_create()
        self._candidate_sift = cv2.SIFT_create(nfeatures=self._sift_nfeatures)
        self._matcher = cv2.BFMatcher(cv2.NORM_L2)
        self._feature_cache: dict[Path, tuple[tuple[cv2.KeyPoint, ...], np.ndarray] | None] = {}

    @property
    def minimum_inliers(self) -> int:
        return self._minimum_inliers

    @property
    def minimum_inlier_ratio(self) -> float:
        return self._minimum_inlier_ratio

    @staticmethod
    def _grayscale(image: Image.Image) -> np.ndarray:
        normalized = ImageOps.exif_transpose(image).convert("L")
        return np.asarray(normalized, dtype=np.uint8)

    def _candidate_grayscale(self, image: Image.Image) -> np.ndarray:
        normalized = ImageOps.exif_transpose(image).convert("L")
        if max(normalized.size) > self._candidate_max_edge:
            normalized.thumbnail(
                (self._candidate_max_edge, self._candidate_max_edge),
                Image.Resampling.LANCZOS,
            )
        return np.asarray(normalized, dtype=np.uint8)

    def _features_image(
        self,
        image: Image.Image,
    ) -> tuple[tuple[cv2.KeyPoint, ...], np.ndarray] | None:
        keypoints, descriptors = self._sift.detectAndCompute(self._grayscale(image), None)
        if descriptors is None or len(keypoints) < 4:
            return None
        return tuple(keypoints), descriptors

    def _candidate_features_image(
        self,
        image: Image.Image,
    ) -> tuple[tuple[cv2.KeyPoint, ...], np.ndarray] | None:
        keypoints, descriptors = self._candidate_sift.detectAndCompute(
            self._candidate_grayscale(image),
            None,
        )
        if descriptors is None or len(keypoints) < 4:
            return None
        if len(keypoints) > self._sift_nfeatures:
            keypoints = keypoints[: self._sift_nfeatures]
            descriptors = descriptors[: self._sift_nfeatures]
        return tuple(keypoints), descriptors

    def _features_path(
        self,
        path: Path,
    ) -> tuple[tuple[cv2.KeyPoint, ...], np.ndarray] | None:
        resolved = path.resolve()
        if resolved in self._feature_cache:
            return self._feature_cache[resolved]

        features = None
        try:
            with Image.open(resolved) as image:
                image.load()
                features = self._candidate_features_image(image)
        except (OSError, ValueError):
            features = None
        self._feature_cache[resolved] = features
        return features

    def _evidence(
        self,
        *,
        source_asset_id: str,
        panel_features: tuple[tuple[cv2.KeyPoint, ...], np.ndarray],
        candidate_features: tuple[tuple[cv2.KeyPoint, ...], np.ndarray],
    ) -> GeometricVisualEvidence | None:
        panel_keypoints, panel_descriptors = panel_features
        candidate_keypoints, candidate_descriptors = candidate_features
        if len(panel_descriptors) < 2 or len(candidate_descriptors) < 2:
            return None

        pairs = self._matcher.knnMatch(candidate_descriptors, panel_descriptors, k=2)
        good_matches = [
            first
            for pair in pairs
            if len(pair) == 2
            for first, second in [pair]
            if first.distance < self._lowe_ratio * second.distance
        ]
        if len(good_matches) < max(4, self._minimum_inliers):
            return None

        source_points = np.float32(
            [candidate_keypoints[match.queryIdx].pt for match in good_matches]
        ).reshape(-1, 1, 2)
        panel_points = np.float32(
            [panel_keypoints[match.trainIdx].pt for match in good_matches]
        ).reshape(-1, 1, 2)
        homography, mask = cv2.findHomography(
            source_points,
            panel_points,
            cv2.RANSAC,
            self._ransac_reprojection_threshold,
        )
        if homography is None or mask is None or not np.isfinite(homography).all():
            return None

        inliers = int(mask.ravel().sum())
        inlier_ratio = inliers / len(good_matches)
        if inliers < self._minimum_inliers or inlier_ratio < self._minimum_inlier_ratio:
            return None

        support = min(1.0, inliers / 24.0)
        score = min(1.0, max(0.0, 0.65 * inlier_ratio + 0.35 * support))
        return GeometricVisualEvidence(
            source_asset_id=source_asset_id,
            score=score,
            good_matches=len(good_matches),
            inliers=inliers,
            inlier_ratio=inlier_ratio,
        )

    def rank(
        self,
        *,
        panel_image: Image.Image,
        candidates: Sequence[tuple[OriginalAssetData, str | Path]],
        top_k: int = 5,
    ) -> tuple[GeometricVisualEvidence, ...]:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")

        panel_features = self._features_image(panel_image)
        if panel_features is None:
            return ()

        ranked: list[GeometricVisualEvidence] = []
        for asset, candidate_path in candidates:
            path = Path(candidate_path)
            if not path.is_file():
                continue
            candidate_features = self._features_path(path)
            if candidate_features is None:
                continue
            evidence = self._evidence(
                source_asset_id=asset.id,
                panel_features=panel_features,
                candidate_features=candidate_features,
            )
            if evidence is not None:
                ranked.append(evidence)

        ranked.sort(
            key=lambda item: (
                -item.score,
                -item.inliers,
                -item.inlier_ratio,
                item.source_asset_id,
            )
        )
        return tuple(ranked[:top_k])
