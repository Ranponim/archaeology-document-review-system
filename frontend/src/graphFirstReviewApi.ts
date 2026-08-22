import type { ReviewRound, RunTriggerResponse } from './api';

export type GraphFirstRoundPayload = {
  bodyVersionId: string;
  referenceCorpusId: string;
  notes?: string | null;
};

export type GraphFirstRunPayload = {
  reviewRoundId: string;
  enableAiReview?: boolean;
  enableVlm?: boolean;
};

async function readJson<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload?.detail === 'string' ? payload.detail : `http_${response.status}`;
    throw new Error(detail);
  }
  return payload as T;
}

export async function createGraphFirstReviewRound(
  projectId: string,
  payload: GraphFirstRoundPayload,
): Promise<ReviewRound> {
  const response = await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/rounds`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      body_version_id: payload.bodyVersionId,
      reference_corpus_id: payload.referenceCorpusId,
      notes: payload.notes ?? null,
    }),
  });
  return readJson<ReviewRound>(response);
}

export async function triggerGraphFirstRun(
  projectId: string,
  payload: GraphFirstRunPayload,
): Promise<RunTriggerResponse> {
  const response = await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      review_round_id: payload.reviewRoundId,
      enable_ai_review: payload.enableAiReview ?? false,
      enable_vlm: payload.enableVlm ?? false,
    }),
  });
  return readJson<RunTriggerResponse>(response);
}
