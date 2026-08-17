import { type CSSProperties, useState } from 'react';
import type { VisualAssetMetadata } from '../api';

type Props = {
  asset?: VisualAssetMetadata | null;
  title: string;
  subtitle?: string;
  testIdPrefix: string;
  fallbackMessage?: string;
};

/**
 * Compute the bbox highlight style for a visual asset.
 *
 * `bbox` is normalized (0..1, PDF top-left origin). The overlay is positioned
 * with percentages so it stays aligned with the image at any display size, and
 * the pixel values derived from `renderWidth`/`renderHeight` are exposed as CSS
 * custom properties so the coordinate math is auditable (review §9 / Test D).
 */
export function bboxOverlayStyle(asset: VisualAssetMetadata): CSSProperties {
  const bbox = asset.bbox ?? [0, 0, 1, 1];
  const [x0, y0, x1, y1] = bbox;
  const rw = asset.renderWidth ?? 1;
  const rh = asset.renderHeight ?? 1;
  return {
    left: `${(x0 * 100).toFixed(3)}%`,
    top: `${(y0 * 100).toFixed(3)}%`,
    width: `${((x1 - x0) * 100).toFixed(3)}%`,
    height: `${((y1 - y0) * 100).toFixed(3)}%`,
    '--bbox-left-px': `${(x0 * rw).toFixed(1)}px`,
    '--bbox-top-px': `${(y0 * rh).toFixed(1)}px`,
    '--bbox-width-px': `${((x1 - x0) * rw).toFixed(1)}px`,
    '--bbox-height-px': `${((y1 - y0) * rh).toFixed(1)}px`,
  } as CSSProperties;
}

export function VisualAssetPane({
  asset,
  title,
  subtitle,
  testIdPrefix,
  fallbackMessage = '시각 에셋 렌더링 준비 중',
}: Props) {
  const [imgError, setImgError] = useState(false);
  const [zoomLevel, setZoomLevel] = useState(1);

  if (!asset || !asset.imageUrl || imgError) {
    return (
      <div className="visual-asset-pane fallback-pane" data-testid={`${testIdPrefix}-pane`}>
        <div className="visual-asset-header">
          <span className="visual-asset-title">{title}</span>
          {subtitle && <span className="visual-asset-subtitle">{subtitle}</span>}
        </div>

        <div className="visual-asset-fallback-box" data-testid={`${testIdPrefix}-fallback`}>
          <div className="fallback-icon">🖼️</div>
          <p className="fallback-main-msg">
            {imgError ? '해당 에셋 렌더 없음 (이미지 로드 실패)' : fallbackMessage}
          </p>
          <p className="fallback-sub-msg">
            시각 에셋 렌더링이 완료되지 않았거나 원본 파일에서 추출 중입니다. 아래 메타데이터 정보를 참조하세요.
          </p>
        </div>

        {asset && (
          <div className="pane-meta-grid">
            {asset.printedIdentifier && (
              <div className="meta-item">
                <span className="meta-label">인쇄 식별자:</span>
                <span className="meta-value">{asset.printedIdentifier}</span>
              </div>
            )}
            {asset.physicalPage != null && (
              <div className="meta-item">
                <span className="meta-label">물리 페이지:</span>
                <span className="meta-value">{asset.physicalPage}</span>
              </div>
            )}
            {asset.caption && (
              <div className="meta-item">
                <span className="meta-label">캡션:</span>
                <span className="meta-value">{asset.caption}</span>
              </div>
            )}
            {asset.bbox && (
              <div className="meta-item">
                <span className="meta-label">BBOX 좌표:</span>
                <span className="meta-value">[{asset.bbox.map((v) => (typeof v === 'number' ? v.toFixed(2) : String(v))).join(', ')}]</span>
              </div>
            )}
            {asset.sourceSha256 && (
              <div className="meta-item hash-item">
                <span className="meta-label">원본 SHA-256:</span>
                <span className="meta-value sha-code">{asset.sourceSha256}</span>
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  const hasBbox = Array.isArray(asset.bbox) && asset.bbox.length === 4;
  const overlayStyle = hasBbox ? bboxOverlayStyle(asset) : undefined;
  const aspectRatio =
    asset.renderWidth && asset.renderHeight
      ? `${asset.renderWidth} / ${asset.renderHeight}`
      : undefined;

  return (
    <div className="visual-asset-pane" data-testid={`${testIdPrefix}-pane`}>
      <div className="visual-asset-header">
        <div className="header-left">
          <span className="visual-asset-title">{title}</span>
          {subtitle && <span className="visual-asset-subtitle">{subtitle}</span>}
        </div>
        <div className="visual-zoom-controls">
          <button
            type="button"
            className="btn-zoom"
            onClick={() => setZoomLevel((prev) => Math.min(3, +(prev + 0.25).toFixed(2)))}
            title="확대"
            aria-label="확대"
          >
            +
          </button>
          <span className="zoom-level-text">{Math.round(zoomLevel * 100)}%</span>
          <button
            type="button"
            className="btn-zoom"
            onClick={() => setZoomLevel((prev) => Math.max(0.5, +(prev - 0.25).toFixed(2)))}
            title="축소"
            aria-label="축소"
          >
            -
          </button>
          {zoomLevel !== 1 && (
            <button
              type="button"
              className="btn-zoom-reset"
              onClick={() => setZoomLevel(1)}
              title="원래 크기"
            >
              초기화
            </button>
          )}
        </div>
      </div>

      <div
        className="visual-asset-frame"
        style={aspectRatio ? { aspectRatio } : undefined}
      >
        <div
          className="visual-asset-zoom-wrap"
          style={{
            transform: `scale(${zoomLevel})`,
            transformOrigin: 'top left',
            width: '100%',
            height: '100%',
            position: 'relative',
          }}
        >
          <img
            className="visual-asset-img"
            src={asset.imageUrl}
            alt={asset.caption ?? asset.printedIdentifier ?? title}
            data-testid={`${testIdPrefix}-img`}
            onError={() => setImgError(true)}
          />
          {hasBbox && (
            <div
              className="visual-asset-bbox"
              style={overlayStyle}
              data-testid={`${testIdPrefix}-bbox`}
            />
          )}
        </div>
      </div>

      <div className="pane-meta-grid">
        {asset.printedIdentifier && (
          <div className="meta-item">
            <span className="meta-label">인쇄 식별자:</span>
            <span className="meta-value">{asset.printedIdentifier}</span>
          </div>
        )}
        {asset.physicalPage != null && (
          <div className="meta-item">
            <span className="meta-label">물리 페이지:</span>
            <span className="meta-value">{asset.physicalPage}</span>
          </div>
        )}
        {asset.caption && (
          <div className="meta-item">
            <span className="meta-label">캡션:</span>
            <span className="meta-value">{asset.caption}</span>
          </div>
        )}
        {asset.sourceSha256 && (
          <div className="meta-item hash-item">
            <span className="meta-label">원본 SHA-256:</span>
            <span className="meta-value sha-code">{asset.sourceSha256}</span>
          </div>
        )}
      </div>
    </div>
  );
}
