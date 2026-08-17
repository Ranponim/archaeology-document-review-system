import { ApiError, type UploadAccepted } from './api';

/**
 * Upload one immutable source asset.
 *
 * Review ordering belongs to ReviewRound.sequence, not DocumentVersion.stage.
 * `stage=source` is retained only for the existing backend upload contract and
 * must never be derived from round count or exposed as 1차/2차/3차 UI.
 */
export async function uploadDocumentRevisionNeutral(
  projectId: string,
  file: File,
  kind: string,
): Promise<UploadAccepted> {
  const body = new FormData();
  body.append('file', file);
  const params = new URLSearchParams({ kind, stage: 'source' });
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/documents?${params.toString()}`,
    { method: 'POST', body },
  );

  if (response.ok) {
    return response.json() as Promise<UploadAccepted>;
  }

  let code = 'server_error';
  try {
    const payload = (await response.json()) as { code?: string; detail?: string };
    code = payload.code ?? payload.detail ?? code;
  } catch {
    // Keep sanitized fallback.
  }
  throw new ApiError(code);
}
