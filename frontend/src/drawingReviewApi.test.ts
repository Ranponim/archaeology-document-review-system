import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchDrawingReviews, resolveDrawingReview } from './drawingReviewApi';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('drawing review API', () => {
  it('fetches project-scoped pending drawing reviews', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await fetchDrawingReviews('project / 1');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/projects/project%20%2F%201/drawing-reviews',
    );
  });

  it('posts an explicit human resolution with encoded source id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          source_asset_id: 'source/a',
          action: 'choose',
          candidate_id: 'candidate:53',
          final_status: 'HUMAN_VERIFIED',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    await resolveDrawingReview('project 1', 'source/a', {
      action: 'choose',
      candidate_id: 'candidate:53',
      reviewer: 'human',
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      '/api/v1/projects/project%201/drawing-reviews/source%2Fa/resolve',
    );
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({
      action: 'choose',
      candidate_id: 'candidate:53',
      reviewer: 'human',
    });
  });

  it('propagates HTTP errors using existing fetch convention', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'review_conflict' }), {
        status: 409,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      resolveDrawingReview('project-1', 'source-a', {
        action: 'none',
        candidate_id: null,
        reviewer: 'human',
      }),
    ).rejects.toThrow('review_conflict');
  });
});
