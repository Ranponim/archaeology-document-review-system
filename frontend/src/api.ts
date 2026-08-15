export type Project = {
  id: string;
  name: string;
  internalCode: string | null;
};

export type DocumentVersion = {
  id: string;
  documentId: string;
  originalName: string;
  mimeType: string;
  sizeBytes: number;
  stage: 'source';
};

export type AnalysisRun = {
  id: string;
  status: string;
  step: string;
  documentVersionId: string;
  errorCode: string | null;
  retryable: boolean;
};

export type ProjectDetail = Project & {
  documentVersions: DocumentVersion[];
  analysisRuns: AnalysisRun[];
};

type UploadAccepted = {
  documentVersionId: string;
  analysisRunId: string;
};

type ErrorBody = {
  code?: string;
};

export class ApiError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.name = 'ApiError';
    this.code = code;
  }
}

async function decode<T>(response: Response): Promise<T> {
  if (response.ok) {
    return response.json() as Promise<T>;
  }

  let code = 'server_error';
  try {
    const body = (await response.json()) as ErrorBody;
    if (body.code === 'input_error' || body.code === 'server_error') {
      code = body.code;
    }
  } catch {
    // The UI deliberately exposes only the fixed public failure code.
  }
  throw new ApiError(code);
}

export async function createProject(name: string): Promise<Project> {
  const response = await fetch('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  return decode<Project>(response);
}

export async function uploadDocument(
  projectId: string,
  file: File,
): Promise<UploadAccepted> {
  const body = new FormData();
  body.append('file', file);
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/documents?stage=source`,
    { method: 'POST', body },
  );
  return decode<UploadAccepted>(response);
}

export async function getProject(projectId: string): Promise<ProjectDetail> {
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}`);
  return decode<ProjectDetail>(response);
}
