import { afterEach, describe, expect, it, vi } from 'vitest';

import { triggerProofreadingRun, uploadDocument } from './api';

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

describe('uploadDocument revision neutrality', () => {
  it('uploads one asset without deriving a 1차/2차/3차 stage from review rounds', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ documentVersionId: 'plate_v2', analysisRunId: 'ingest_2' }),
        { status: 202, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    await uploadDocument(
      'proj_1',
      new File(['pdf'], '도판-수정.pdf', { type: 'application/pdf' }),
      'plate_book',
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/projects/proj_1/documents?kind=plate_book&stage=source');
    expect(init.method).toBe('POST');
  });
});
