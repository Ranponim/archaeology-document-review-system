import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DrawingIdentityReviewPanel } from './DrawingIdentityReviewPanel';

const apiMocks = vi.hoisted(() => ({
  fetchDrawingReviews: vi.fn(),
  resolveDrawingReview: vi.fn(),
}));

vi.mock('../drawingReviewApi', () => apiMocks);

const reviewCase = {
  source_asset_id: 'source-a',
  source_name: 'source-a.ai',
  source_image_url: '/source.png',
  source_text: '2지점 1호 토광묘 평단면',
  codex_candidate_id: 'candidate:52',
  codex_confidence: 0.98,
  codex_summary: '도면 52가 지점과 유구가 가장 잘 일치합니다.',
  candidates: [
    {
      candidate_id: 'candidate:52',
      publication_kind: 'drawing',
      number: '52',
      caption: '도면 52. 2지점 1호 토광묘',
      image_url: '/52.png',
      local_score: 18,
      evidence_summary: ['2지점 일치', '1호 토광묘 일치'],
      contradiction_summary: [],
    },
    {
      candidate_id: 'candidate:53',
      publication_kind: 'drawing',
      number: '53',
      caption: '도면 53. 2지점 2호 토광묘',
      image_url: '/53.png',
      local_score: 17,
      evidence_summary: ['2지점 일치'],
      contradiction_summary: ['유구 번호 불일치 가능성'],
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.fetchDrawingReviews.mockResolvedValue([reviewCase]);
  apiMocks.resolveDrawingReview.mockResolvedValue({
    source_asset_id: 'source-a',
    action: 'approve',
    candidate_id: 'candidate:52',
    final_status: 'HUMAN_VERIFIED',
  });
});

describe('DrawingIdentityReviewPanel', () => {
  it('shows source, Codex judgement and comparable candidates', async () => {
    render(<DrawingIdentityReviewPanel projectId="project-1" />);

    expect(await screen.findByText('source-a.ai')).toBeInTheDocument();
    expect(screen.getByText('Codex 98%')).toBeInTheDocument();
    expect(screen.getByText(/도면 52가 지점과 유구/)).toBeInTheDocument();
    expect(screen.getByText('도면 52')).toBeInTheDocument();
    expect(screen.getByText('도면 53')).toBeInTheDocument();
    expect(screen.getByText('1호 토광묘 일치')).toBeInTheDocument();
    expect(screen.getByText('유구 번호 불일치 가능성')).toBeInTheDocument();
    expect(screen.getByAltText('source-a.ai 원본')).toHaveAttribute('src', '/source.png');
    expect(screen.getByAltText('도면 52 후보')).toHaveAttribute('src', '/52.png');
  });

  it('approves Codex selected candidate and chooses a different one explicitly', async () => {
    const user = userEvent.setup();
    render(<DrawingIdentityReviewPanel projectId="project-1" />);

    await user.click(await screen.findByRole('button', { name: '도면 52 승인' }));
    await waitFor(() => {
      expect(apiMocks.resolveDrawingReview).toHaveBeenCalledWith(
        'project-1',
        'source-a',
        { action: 'approve', candidate_id: 'candidate:52', reviewer: 'human' },
      );
    });

    apiMocks.fetchDrawingReviews.mockResolvedValue([reviewCase]);
    apiMocks.resolveDrawingReview.mockClear();
    render(<DrawingIdentityReviewPanel projectId="project-1" />);
    await user.click(await screen.findByRole('button', { name: '도면 53 선택' }));
    await waitFor(() => {
      expect(apiMocks.resolveDrawingReview).toHaveBeenCalledWith(
        'project-1',
        'source-a',
        { action: 'choose', candidate_id: 'candidate:53', reviewer: 'human' },
      );
    });
  });

  it('does not mutate on focus and supports 모두 아님', async () => {
    const user = userEvent.setup();
    render(<DrawingIdentityReviewPanel projectId="project-1" />);

    const card = await screen.findByTestId('drawing-candidate-candidate:52');
    await user.click(card);
    expect(apiMocks.resolveDrawingReview).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: '모두 아님' }));
    await waitFor(() => {
      expect(apiMocks.resolveDrawingReview).toHaveBeenCalledWith(
        'project-1',
        'source-a',
        { action: 'none', candidate_id: null, reviewer: 'human' },
      );
    });
  });

  it('removes a resolved source and shows empty queue', async () => {
    const user = userEvent.setup();
    render(<DrawingIdentityReviewPanel projectId="project-1" />);

    await user.click(await screen.findByRole('button', { name: '도면 52 승인' }));

    expect(await screen.findByText('검수할 도면 없음')).toBeInTheDocument();
  });

  it('shows loading and error states explicitly', async () => {
    let release: (value: unknown) => void = () => undefined;
    apiMocks.fetchDrawingReviews.mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    const { unmount } = render(<DrawingIdentityReviewPanel projectId="project-1" />);
    expect(screen.getByText('도면 검수 불러오는 중…')).toBeInTheDocument();
    release([]);
    unmount();

    apiMocks.fetchDrawingReviews.mockRejectedValue(new Error('server_error'));
    render(<DrawingIdentityReviewPanel projectId="project-1" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('server_error');
  });
});
