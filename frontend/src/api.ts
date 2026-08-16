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
  stage: string;
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

export type UploadAccepted = {
  documentVersionId: string;
  analysisRunId: string;
};

export type Evidence = {
  id: string;
  kind?: string | null;
  sourceSha256?: string | null;
  source_sha256?: string | null;
  documentVersionId?: string | null;
  document_version_id?: string | null;
  pageId?: string | null;
  page_id?: string | null;
  regionId?: string | null;
  region_id?: string | null;
  bbox?: number[] | [number, number, number, number] | null;
  method?: string;
  analysisRunId?: string | null;
  analysis_run_id?: string | null;
  value?: unknown;
  rationale?: string | null;
  confidence?: number;
  versionFrom?: string | null;
  version_from?: string | null;
  versionTo?: string | null;
  version_to?: string | null;
  physicalPageFrom?: number | null;
  physical_page_from?: number | null;
  physicalPageTo?: number | null;
  physical_page_to?: number | null;
  printedPageFrom?: number | null;
  printed_page_from?: number | null;
  printedPageTo?: number | null;
  printed_page_to?: number | null;
  ruleName?: string | null;
  rule_name?: string | null;
  page?: {
    id?: string;
    physical_page?: number;
    printed_page?: number | string;
    header?: string;
    normalized_text?: string;
  };
  document_version?: {
    id?: string;
    original_name?: string;
    stage?: string;
  };
};

export type ReviewDecision = {
  id: string;
  candidateId?: string;
  candidate_id?: string;
  decisionStatus?: string;
  decision_status?: string;
  decision?: string | null;
  note?: string;
  rationale?: string | null;
  reviewer?: string;
  modifiedText?: string | null;
  modified_text?: string | null;
  previousDecisionId?: string | null;
  previous_decision_id?: string | null;
  createdAt?: string | null;
  created_at?: string | null;
};

export type ArchaeologyObject = {
  id: string;
  title?: string;
  object_type?: string;
  objectType?: string;
  plate_number?: string | number;
  plateNumber?: string | number;
  drawing_number?: string | number;
  drawingNumber?: string | number;
  description?: string;
  captions?: string[];
  vlm_verdict?: string;
  properties?: Record<string, unknown>;
};

export type CorrectionCandidate = {
  id: string;
  category?: string;
  ruleCategory?: string | null;
  rule_category?: string | null;
  changeType?: string;
  change_type?: string;
  status: string;
  originalText?: string | null;
  original_text?: string | null;
  proposedText?: string | null;
  proposed_text?: string | null;
  evidence?: Evidence | null;
  evidences?: Evidence[];
  archaeologyObjectId?: string | null;
  archaeology_object_id?: string | null;
  confidence?: number;
  severity?: 'low' | 'medium' | 'high' | string;
  decisions?: ReviewDecision[];
};

export type CandidateFilters = {
  status?: string;
  rule_category?: string;
  archaeology_object_id?: string;
  severity?: string;
};

export type CandidateListResponse = {
  projectId?: string;
  project_id?: string;
  total: number;
  candidates: CorrectionCandidate[];
};

export type TraceabilityResponse = {
  candidateId?: string;
  candidate_id?: string;
  candidate?: CorrectionCandidate | null;
  archaeologyObject?: ArchaeologyObject | null;
  archaeology_object?: ArchaeologyObject | null;
  evidence?: Evidence[] | Evidence | null;
  evidenceChain?: Array<{
    evidence?: Evidence;
    page?: Record<string, unknown>;
    document_version?: Record<string, unknown>;
  }>;
  evidence_chain?: Array<{
    evidence?: Evidence;
    page?: Record<string, unknown>;
    document_version?: Record<string, unknown>;
  }>;
  documentVersionId?: string | null;
  document_version_id?: string | null;
  pageId?: string | null;
  page_id?: string | null;
  bbox?: number[] | null;
  sourceSha256?: string | null;
  source_sha256?: string | null;
  decisions?: ReviewDecision[];
};

export type RunTriggerPayload = {
  bodyVersionId?: string | null;
  body_version_id?: string | null;
  plateVersionId?: string | null;
  plate_version_id?: string | null;
  drawingVersionId?: string | null;
  drawing_version_id?: string | null;
  bodyPdfPath?: string | null;
  body_pdf_path?: string | null;
  platePdfPath?: string | null;
  plate_pdf_path?: string | null;
  drawingPdfPath?: string | null;
  drawing_pdf_path?: string | null;
  enableVlm?: boolean;
  enable_vlm?: boolean;
  enableAiReview?: boolean;
  enable_ai_review?: boolean;
  versionStage?: string;
  version_stage?: string;
};

export type RunTriggerResponse = {
  runId?: string;
  run_id?: string;
  projectId?: string;
  project_id?: string;
  status: string;
  pagesParsed?: number;
  pages_parsed?: number;
  objectsResolved?: number;
  objects_resolved?: number;
  referencesResolved?: number;
  references_resolved?: number;
  candidatesCount?: number;
  candidates_count?: number;
  summary?: Record<string, unknown>;
  errors?: string[];
};

export type ReviewDecisionPayload = {
  decision: string;
  reviewer: string;
  rationale?: string;
  note?: string;
  modifiedText?: string | null;
  modified_text?: string | null;
};

export type ReviewMetrics = {
  projectId?: string;
  project_id?: string;
  totalCandidates?: number;
  total_candidates?: number;
  pendingCandidates?: number;
  pending_candidates?: number;
  acceptedCandidates?: number;
  accepted_candidates?: number;
  rejectedCandidates?: number;
  rejected_candidates?: number;
  modifiedCandidates?: number;
  modified_candidates?: number;
  byCategory?: Record<string, number>;
  by_category?: Record<string, number>;
  bySeverity?: Record<string, number>;
  by_severity?: Record<string, number>;
  byStatus?: Record<string, number>;
  by_status?: Record<string, number>;
  completionRate?: number;
  completion_rate?: number;
  accuracyRate?: number;
  accuracy_rate?: number;
};

type ErrorBody = {
  code?: string;
  detail?: string;
  message?: string;
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
    } else if (body.detail) {
      code = body.detail;
    }
  } catch {
    // The UI exposes clean fallback error codes.
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

export async function triggerProofreadingRun(
  projectId: string,
  payload: Partial<RunTriggerPayload> = {},
): Promise<RunTriggerResponse> {
  const response = await fetch(
    `/api/v1/projects/${encodeURIComponent(projectId)}/runs`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        body_version_id: payload.body_version_id ?? payload.bodyVersionId ?? null,
        plate_version_id: payload.plate_version_id ?? payload.plateVersionId ?? null,
        drawing_version_id: payload.drawing_version_id ?? payload.drawingVersionId ?? null,
        body_pdf_path: payload.body_pdf_path ?? payload.bodyPdfPath ?? null,
        plate_pdf_path: payload.plate_pdf_path ?? payload.platePdfPath ?? null,
        drawing_pdf_path: payload.drawing_pdf_path ?? payload.drawingPdfPath ?? null,
        enable_vlm: payload.enable_vlm ?? payload.enableVlm ?? true,
        enable_ai_review: payload.enable_ai_review ?? payload.enableAiReview ?? true,
        version_stage: payload.version_stage ?? payload.versionStage ?? '1차',
      }),
    },
  );
  return decode<RunTriggerResponse>(response);
}

export async function fetchCandidates(
  projectId: string,
  filters?: CandidateFilters,
): Promise<CandidateListResponse> {
  const params = new URLSearchParams();
  if (filters?.status) params.set('status', filters.status);
  if (filters?.rule_category) params.set('rule_category', filters.rule_category);
  if (filters?.archaeology_object_id) {
    params.set('archaeology_object_id', filters.archaeology_object_id);
  }
  if (filters?.severity) params.set('severity', filters.severity);

  const qs = params.toString();
  const url = `/api/v1/projects/${encodeURIComponent(projectId)}/candidates${qs ? `?${qs}` : ''}`;
  const response = await fetch(url);
  return decode<CandidateListResponse>(response);
}

export async function submitReviewDecision(
  projectId: string,
  candidateId: string,
  payload: ReviewDecisionPayload,
): Promise<ReviewDecision> {
  const response = await fetch(
    `/api/v1/projects/${encodeURIComponent(projectId)}/candidates/${encodeURIComponent(candidateId)}/decision`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        decision: payload.decision,
        reviewer: payload.reviewer,
        rationale: payload.rationale ?? payload.note ?? '',
        note: payload.note ?? payload.rationale ?? '',
        modified_text: payload.modified_text ?? payload.modifiedText ?? null,
      }),
    },
  );
  return decode<ReviewDecision>(response);
}

export async function fetchTraceability(
  projectId: string,
  candidateId: string,
): Promise<TraceabilityResponse> {
  const response = await fetch(
    `/api/v1/projects/${encodeURIComponent(projectId)}/candidates/${encodeURIComponent(candidateId)}/traceability`,
  );
  return decode<TraceabilityResponse>(response);
}

export async function fetchMetrics(projectId: string): Promise<ReviewMetrics> {
  const response = await fetch(
    `/api/v1/projects/${encodeURIComponent(projectId)}/metrics`,
  );
  return decode<ReviewMetrics>(response);
}
