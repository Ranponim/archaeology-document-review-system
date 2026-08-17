import { afterEach, describe, expect, it, vi } from 'vitest';

import { triggerProofreadingRun } from './api';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('triggerProofreadingRun ReviewRound authority', () => {
  it('posts the explicitly selected review round and no version selectors', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ runId: 'run_1', projectId: 'proj_1', status: 'queued', warnings: [] }),
        { status: 202, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    await triggerProofreadingRun('proj_1', {
      review_round_id: 'round_selected',
      enable_vlm: false,
      enable_ai_review: true,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/projects/proj_1/runs');
    expect(JSON.parse(String(init.body))).toEqual({
      review_round_id: 'round_selected',
      enable_vlm: false,
      enable_ai_review: true,
    });
  });

  it('fails closed instead of silently selecting the latest round', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    await expect(triggerProofreadingRun('proj_1', {})).rejects.toMatchObject({
      code: 'review_round_required',
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
