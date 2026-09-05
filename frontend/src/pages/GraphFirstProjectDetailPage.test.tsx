import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Project, ProjectDetail } from '../api';
import { GraphFirstProjectDetailPage } from './GraphFirstProjectDetailPage';

const apiMocks = vi.hoisted(() => ({
  getProject: vi.fn(),
  uploadDocument: vi.fn(),
  fetchCandidates: vi.fn(),
  fetchReviewRounds: vi.fn(),
  approveReviewRound: vi.fn(),
  retryAnalysisRun: vi.fn(),
}));

const graphMocks = vi.hoisted(() => ({
  createGraphFirstReviewRound: vi.fn(),
  triggerGraphFirstRun: vi.fn(),
}));

const drawingReviewMocks = vi.hoisted(() => ({
  fetchDrawingReviews: vi.fn(),
  resolveDrawingReview: vi.fn(),
}));

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return { ...actual, ...apiMocks };
});

vi.mock('../graphFirstReviewApi', () => graphMocks);
vi.mock('../drawingReviewApi', () => drawingReviewMocks);

vi.mock('../components/ReferenceCorpusPanel', () => ({
  ReferenceCorpusPanel: () => <div>Reference corpus fixture</div>,
}));

const project: Project = { id: 'project-1', name: '산노리', internalCode: null };

function detail(): ProjectDetail {
  return {
    ...project,
    documents: [],
    documentVersions: [],
    analysisRuns: [],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.getProject.mockResolvedValue(detail());
  apiMocks.fetchCandidates.mockResolvedValue({ total: 0, candidates: [] });
  apiMocks.fetchReviewRounds.mockResolvedValue([]);
  drawingReviewMocks.resolveDrawingReview.mockResolvedValue({
    source_asset_id: 'source-a',
    action: 'approve',
    candidate_id: 'candidate:52',
    final_status: 'HUMAN_VERIFIED',
  });
});

describe('GraphFirstProjectDetailPage drawing identity review integration', () => {
  it('mounts the drawing identity comparison workflow in a labeled section', async () => {
    drawingReviewMocks.fetchDrawingReviews.mockResolvedValue([
      {
        source_asset_id: 'source-a',
        source_name: 'source-a.ai',
        source_image_url: '/source.png',
        source_text: '2지점 1호 토광묘',
        codex_candidate_id: 'candidate:52',
        codex_confidence: 0.98,
        codex_summary: '도면 52가 가장 일치합니다.',
        candidates: [
          {
            candidate_id: 'candidate:52',
            publication_kind: 'drawing',
            number: '52',
            caption: '도면 52. 2지점 1호 토광묘',
            image_url: '/52.png',
            local_score: 18,
            evidence_summary: ['2지점 일치'],
            contradiction_summary: [],
          },
        ],
      },
    ]);

    render(<GraphFirstProjectDetailPage project={project} />);

    const section = await screen.findByRole('region', { name: '도면 ID 검수' });
    expect(within(section).getByText('source-a.ai')).toBeInTheDocument();
    expect(within(section).getByText('Codex 98%')).toBeInTheDocument();
    expect(within(section).getByRole('button', { name: '도면 52 승인' })).toBeInTheDocument();
  });

  it('keeps the review section visible when the queue is empty', async () => {
    drawingReviewMocks.fetchDrawingReviews.mockResolvedValue([]);

    render(<GraphFirstProjectDetailPage project={project} />);

    const section = await screen.findByRole('region', { name: '도면 ID 검수' });
    expect(within(section).getByText('검수할 도면 없음')).toBeInTheDocument();
  });
});
