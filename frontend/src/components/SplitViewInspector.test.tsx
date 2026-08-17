import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { CandidateVisualBundle, CorrectionCandidate } from '../api';
import { SplitViewInspector } from './SplitViewInspector';

const apiMocks = vi.hoisted(() => ({
  fetchVisualBundle: vi.fn(),
  submitReviewDecision: vi.fn(),
}));

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return { ...actual, ...apiMocks };
});

const candidate: CorrectionCandidate = {
  id: 'cand_1',
  rule_category: 'figure_plate_table_photo_ref',
  status: 'pending_review',
  original_text: '도판 45',
  proposed_text: '도판 45',
};

const bundle: CandidateVisualBundle = {
  candidateId: 'cand_1',
  source: {
    assetType: 'page',
    imageUrl: '/api/v1/assets/pages/ver_body_p10/render',
    documentVersionId: 'ver_body',
    sourceSha256: 'sha256_body',
    physicalPage: 10,
    printedIdentifier: '10',
    regionId: 'ver_body_p10',
    bbox: [0.1, 0.1, 0.5, 0.2],
    renderWidth: 1191,
    renderHeight: 1686,
  },
  canonical: {
    assetType: 'plate_panel',
    imageUrl: '/api/v1/assets/plate-panels/plate_45_panel_1/render',
    documentVersionId: 'ver_plate',
    sourceSha256: 'sha256_plate',
    physicalPage: 47,
    printedIdentifier: '【도판 45】',
    regionId: 'plate_45_panel_1',
    bbox: [0.1, 0.1, 0.5, 0.5],
    caption: '조사 전',
    renderWidth: 1191,
    renderHeight: 1684,
  },
};

describe('SplitViewInspector real visual split view', () => {
  it('renders body page and panel images from the visual-bundle render routes, not filesystem paths', async () => {
    apiMocks.fetchVisualBundle.mockResolvedValue(bundle);
    render(<SplitViewInspector projectId="proj_1" candidate={candidate} />);

    const sourceImg = await screen.findByTestId('source-img');
    const canonicalImg = await screen.findByTestId('canonical-img');

    expect(sourceImg.getAttribute('src')).toBe(
      '/api/v1/assets/pages/ver_body_p10/render',
    );
    expect(canonicalImg.getAttribute('src')).toBe(
      '/api/v1/assets/plate-panels/plate_45_panel_1/render',
    );

    const fsPath = /^(\/data\/|\/Users\/|\/tmp\/|\/var\/|\/private\/|file:\/\/)/;
    expect(sourceImg.getAttribute('src')).not.toMatch(fsPath);
    expect(canonicalImg.getAttribute('src')).not.toMatch(fsPath);
  });

  it('renders the bbox highlight at the correct normalized position using renderWidth/Height', async () => {
    apiMocks.fetchVisualBundle.mockResolvedValue(bundle);
    render(<SplitViewInspector projectId="proj_1" candidate={candidate} />);

    const sourceBbox = await screen.findByTestId('source-bbox');
    expect(sourceBbox.style.left).toBe('10%');
    expect(sourceBbox.style.top).toBe('10%');
    expect(sourceBbox.style.width).toBe('40%');
    expect(sourceBbox.style.height).toBe('10%');

    expect(sourceBbox.style.getPropertyValue('--bbox-left-px')).toBe('119.1px');
    expect(sourceBbox.style.getPropertyValue('--bbox-top-px')).toBe('168.6px');
    expect(sourceBbox.style.getPropertyValue('--bbox-width-px')).toBe('476.4px');
    expect(sourceBbox.style.getPropertyValue('--bbox-height-px')).toBe('168.6px');
  });

  it('renders the canonical drawing in the drawing section when the canonical asset is a drawing', async () => {
    apiMocks.fetchVisualBundle.mockResolvedValue({
      candidateId: 'cand_1',
      source: bundle.source,
      canonical: {
        assetType: 'drawing_region',
        imageUrl: '/api/v1/assets/drawing-regions/draw_30_region_1/render',
        documentVersionId: 'ver_draw',
        sourceSha256: 'sha256_draw',
        printedIdentifier: '【도면 30】',
        regionId: 'draw_30_region_1',
        bbox: [0.2, 0.2, 0.6, 0.6],
        caption: "토층 A-A'",
        renderWidth: 1191,
        renderHeight: 1684,
      },
    });
    render(<SplitViewInspector projectId="proj_1" candidate={candidate} />);

    const drawingImg = await screen.findByTestId('drawing-img');
    expect(drawingImg.getAttribute('src')).toBe(
      '/api/v1/assets/drawing-regions/draw_30_region_1/render',
    );
  });

  it('renders informative fallback when visual bundle assets are unavailable', async () => {
    apiMocks.fetchVisualBundle.mockResolvedValue({
      candidateId: 'cand_1',
      source: null,
      canonical: null,
    });
    render(<SplitViewInspector projectId="proj_1" candidate={candidate} />);

    const sourceFallback = await screen.findByTestId('source-fallback');
    expect(sourceFallback).toBeInTheDocument();
    expect(screen.getByText(/본문 시각 에셋 렌더링 준비 중/)).toBeInTheDocument();

    const canonicalFallback = await screen.findByTestId('canonical-fallback');
    expect(canonicalFallback).toBeInTheDocument();
    expect(screen.getByText(/해당 에셋 렌더 없음/)).toBeInTheDocument();
  });

  it('supports zoom controls on rendered visual assets', async () => {
    apiMocks.fetchVisualBundle.mockResolvedValue(bundle);
    render(<SplitViewInspector projectId="proj_1" candidate={candidate} />);

    await screen.findByTestId('source-img');
    const zoomButtons = screen.getAllByRole('button', { name: '확대' });
    expect(zoomButtons.length).toBeGreaterThan(0);
  });
});

