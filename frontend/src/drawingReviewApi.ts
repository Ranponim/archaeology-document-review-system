export type DrawingReviewCandidate = {
  candidate_id: string;
  publication_kind: string;
  number: string;
  caption: string;
  image_url: string | null;
  local_score: number;
  evidence_summary: string[];
  contradiction_summary: string[];
};

export type DrawingReviewCase = {
  source_asset_id: string;
  source_name: string;
  source_image_url: string | null;
  source_text: string;
  codex_candidate_id: string | null;
  codex_confidence: number | null;
  codex_summary: string | null;
  candidates: DrawingReviewCandidate[];
};

export type DrawingReviewResolveInput = {
  action: 'approve' | 'choose' | 'none';
  candidate_id: string | null;
  reviewer: string;
};

export type DrawingReviewResolution = {
  source_asset_id: string;
  action: 'approve' | 'choose' | 'none';
  candidate_id: string | null;
  final_status: 'HUMAN_VERIFIED' | 'HUMAN_UNRESOLVED';
};

async function readJson<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail =
      typeof payload?.detail === 'string'
        ? payload.detail
        : `http_${response.status}`;
    throw new Error(detail);
  }
  return payload as T;
}

export async function fetchDrawingReviews(
  projectId: string,
): Promise<DrawingReviewCase[]> {
  const response = await fetch(
    `/api/v1/projects/${encodeURIComponent(projectId)}/drawing-reviews`,
  );
  return readJson<DrawingReviewCase[]>(response);
}

export async function resolveDrawingReview(
  projectId: string,
  sourceAssetId: string,
  input: DrawingReviewResolveInput,
): Promise<DrawingReviewResolution> {
  const response = await fetch(
    `/api/v1/projects/${encodeURIComponent(projectId)}/drawing-reviews/${encodeURIComponent(sourceAssetId)}/resolve`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
  );
  return readJson<DrawingReviewResolution>(response);
}
