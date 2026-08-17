import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { CandidateVisualBundle, CorrectionCandidate, TraceabilityResponse } from '../api';
import { SplitViewInspector } from './SplitViewInspector';

const apiMocks = vi.hoisted(() => ({
  fetchVisualBundle: vi.fn(),
  submitReviewDecision: vi.fn(),
}));

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return { ...actual, ...apiMocks };
});

function candidate(overrides: Partial<CorrectionCandidate> = {}): CorrectionCandidate {
  return {
    id: 'cand_numeric',
    rule_category: 'numeric_value',
    status: 'pending_review',
    original_text: '길이 220cm',
    proposed_text: '길이 210cm',
    confidence: 0.95,
    ...overrides,
  };
}

const previousPage = {
  assetType: 'page',
  imageUrl: '/api/v1/assets/pages/body_v2_p10/render',
  documentVersionId: 'body_v2',
  sourceSha256: 'sha_v2',
  physicalPage: 10,
  regionId: 'body_v2_p10',
};

const currentPage = {
  assetType: 'page',
  imageUrl: '/api/v1/assets/pages/body_v3_p10/render',
  documentVersionId: 'body_v3',
  sourceSha256: 'sha_v3',
  physicalPage: 10,
  regionId: 'body_v3_p10',
};

describe('SplitViewInspector evidence-aware comparison modes', () => {
  it('shows previous/current body evidence for a numeric version change and never an empty plate pane', async () => {
    apiMocks.fetchVisualBundle.mockResolvedValue({
      candidateId: 'cand_numeric',
      comparisonType: 'version_change',
      source: previousPage,
      comparison: currentPage,
      canonical: null,
      reference: null,
      renderStatus: 'ready',
      unresolvedReason: null,
    } as unknown as CandidateVisualBundle);

    render(<SplitViewInspector projectId="p1" candidate={candidate()} />);

    expect(await screen.findByText(/비교 근거: 본문 수정본 간 비교/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '이전 본문' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '현재 본문' })).toBeInTheDocument();
    expect(await screen.findByTestId('comparison-img')).toHaveAttribute(
      'src',
      '/api/v1/assets/pages/body_v3_p10/render',
    );
    expect(screen.queryByText(/표준 도판 \/ 사진/)).not.toBeInTheDocument();
    expect(screen.queryByText(/해당 에셋 렌더 없음/)).not.toBeInTheDocument();
  });

  it('shows exact plate reference identity when the graph resolved a plate target', async () => {
    apiMocks.fetchVisualBundle.mockResolvedValue({
      candidateId: 'cand_plate',
      comparisonType: 'plate_reference',
      source: currentPage,
      comparison: null,
      canonical: {
        assetType: 'plate',
        imageUrl: '/api/v1/assets/plates/plate_45/render',
        documentVersionId: 'plate_v1',
        sourceSha256: 'plate_sha',
        physicalPage: 45,
        printedIdentifier: '【도판 45】',
        regionId: 'plate_45',
      },
      reference: {
        type: 'plate',
        number: '45',
        referenceId: 'ref_plate_45',
        targetId: 'plate_45',
      },
      renderStatus: 'ready',
      unresolvedReason: null,
    } as unknown as CandidateVisualBundle);

    render(
      <SplitViewInspector
        projectId="p1"
        candidate={candidate({
          id: 'cand_plate',
          rule_category: 'figure_plate_table_photo_ref',
          original_text: '본문 도판 45 확인',
          proposed_text: '본문 도판 45 확인',
        })}
      />,
    );

    expect(await screen.findByText(/비교 근거: 본문 ↔ 도판 45/)).toBeInTheDocument();
    expect(screen.getByText(/plate_45/)).toBeInTheDocument();
    expect(await screen.findByTestId('canonical-img')).toHaveAttribute(
      'src',
      '/api/v1/assets/plates/plate_45/render',
    );
  });

  it('shows exact drawing reference identity when the graph resolved a drawing target', async () => {
    apiMocks.fetchVisualBundle.mockResolvedValue({
      candidateId: 'cand_drawing',
      comparisonType: 'drawing_reference',
      source: currentPage,
      comparison: null,
      canonical: {
        assetType: 'drawing',
        imageUrl: '/api/v1/assets/drawings/drawing_30/render',
        documentVersionId: 'drawing_v1',
        sourceSha256: 'drawing_sha',
        physicalPage: 30,
        printedIdentifier: '【도면 30】',
        regionId: 'drawing_30',
      },
      reference: {
        type: 'drawing',
        number: '30',
        referenceId: 'ref_drawing_30',
        targetId: 'drawing_30',
      },
      renderStatus: 'ready',
      unresolvedReason: null,
    } as unknown as CandidateVisualBundle);

    render(
      <SplitViewInspector
        projectId="p1"
        candidate={candidate({
          id: 'cand_drawing',
          rule_category: 'figure_plate_table_photo_ref',
          original_text: '본문 도면 30 확인',
          proposed_text: '본문 도면 30 확인',
        })}
      />,
    );

    expect(await screen.findByText(/비교 근거: 본문 ↔ 도면 30/)).toBeInTheDocument();
    expect(await screen.findByTestId('drawing-img')).toHaveAttribute(
      'src',
      '/api/v1/assets/drawings/drawing_30/render',
    );
  });

  it('renders rule-only evidence as text evidence without a fake visual or fake VLM observation', async () => {
    apiMocks.fetchVisualBundle.mockResolvedValue({
      candidateId: 'cand_text',
      comparisonType: 'text_evidence',
      source: currentPage,
      comparison: null,
      canonical: null,
      reference: null,
      renderStatus: 'not_applicable',
      unresolvedReason: null,
    } as unknown as CandidateVisualBundle);

    const traceability = {
      candidateId: 'cand_text',
      evidence: [
        {
          id: 'ev_rule',
          kind: 'rule_finding',
          method: 'rule',
          rationale: '규칙 기반 수치 불일치',
          confidence: 0.95,
        },
      ],
    } as unknown as TraceabilityResponse;

    render(
      <SplitViewInspector
        projectId="p1"
        candidate={candidate({ id: 'cand_text' })}
        traceability={traceability}
      />,
    );

    expect(await screen.findByText(/비교 근거: 규칙 기반 본문 Evidence/)).toBeInTheDocument();
    expect(screen.queryByText(/표준 도판 \/ 사진/)).not.toBeInTheDocument();
    expect(screen.queryByText(/VLM 비전 분석 관찰 소견/)).not.toBeInTheDocument();
  });

  it('shows VLM observation only when a real vlm_observation evidence exists', async () => {
    apiMocks.fetchVisualBundle.mockResolvedValue({
      candidateId: 'cand_vlm',
      comparisonType: 'text_evidence',
      source: currentPage,
      comparison: null,
      canonical: null,
      reference: null,
      renderStatus: 'not_applicable',
      unresolvedReason: null,
    } as unknown as CandidateVisualBundle);

    const traceability = {
      candidateId: 'cand_vlm',
      evidence: [
        {
          id: 'ev_vlm',
          kind: 'vlm_observation',
          method: 'vlm',
          rationale: '도판 관찰 결과 실제 본문 주장과 불일치',
          confidence: 0.82,
        },
      ],
    } as unknown as TraceabilityResponse;

    render(
      <SplitViewInspector
        projectId="p1"
        candidate={candidate({ id: 'cand_vlm' })}
        traceability={traceability}
      />,
    );

    expect(await screen.findByText(/VLM 비전 분석 관찰 소견/)).toBeInTheDocument();
    expect(
      screen.getByText(/도판 관찰 결과 실제 본문 주장과 불일치/, {
        selector: '.vlm-verdict-text',
      }),
    ).toBeInTheDocument();
  });
});
