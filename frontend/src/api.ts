export type Project = {
  id: string;
  name: string;
  internalCode: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type Document = {
  id: string;
  projectId: string;
  kind: string;
  title: string;
};

export type DocumentVersion = {
  id: string;
  documentId: string;
  originalName: string;
  mimeType: string;
  sizeBytes: number;
  stage: string;
  kind?: string;
};

export type AnalysisRun = {
  id: string;
  status: string;
  step: string;
  documentVersionId: string;
  reviewRoundId?: string | null;
  errorCode: string | null;
  retryable: boolean;
  progressStage?: string | null;
  progressMessage?: string | null;
  currentPage?: number | null;
  totalPages?: number | null;
};

export interface ReviewRound {
  id: string;
  projectId?: string;
  project_id?: string;
  sequence: number;
  status: 'draft' | 'reviewing' | 'revisions_requested' | 'approved';
  bodyVersionId?: string | null;
  body_version_id?: string | null;
  plateVersionId?: string | null;
  plate_version_id?: string | null;
  drawingVersionId?: string | null;
  drawing_version_id?: string | null;
  createdAt?: string | null;
  created_at?: string | null;
  approvedAt?: string | null;
  approved_at?: string | null;
  notes?: string | null;
}

export interface CreateReviewRoundPayload {
  body_version_id?: string | null;
  bodyVersionId?: string | null;
  plate_version_id?: string | null;
  plateVersionId?: string | null;
  drawing_version_id?: string | null;
  drawingVersionId?: string | null;
  notes?: string | null;
}

export type ProjectDetail = Project & {
  documents: Document[];
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
    sha256?: string;
  };
};

export type ReviewDecisionValue = 'accepted' | 'rejected' | 'modified' | 'deferred';

export type ReviewDecision = {
  id: string;
  candidateId?: string;
  candidate_id?: string;
  decisionStatus?: ReviewDecisionValue;
  decision_status?: ReviewDecisionValue;
  decision?: ReviewDecisionValue | null;
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
  canonical_name?: string;
  site?: string;
  period?: string;
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
  findingFingerprint?: string | null;
  decisions?: ReviewDecision[];
  latestDecision?: ReviewDecision | null;
  latest_decision?: ReviewDecision | null;
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

export type CanonicalPathEdge = {
  from: string;
  from_label?: string;
  edge: string;
  to: string;
  to_label?: string;
  source?: Record<string, unknown>;
  target?: Record<string, unknown>;
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
  latestDecision?: ReviewDecision | null;
  latest_decision?: ReviewDecision | null;
  canonicalPath?: CanonicalPathEdge[];
  canonical_path?: CanonicalPathEdge[];
};

export type RunTriggerPayload = {
  reviewRoundId?: string | null;
  review_round_id?: string | null;
  bodyVersionId?: string | null;
  body_version_id?: string | null;
  plateVersionId?: string | null;
  plate_version_id?: string | null;
  drawingVersionId?: string | null;
  drawing_version_id?: string | null;
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
  reviewRoundId?: string | null;
  review_round_id?: string | null;
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
  warnings?: string[];
};

export type AnalysisRunDiagnostics = {
  id?: string;
  status?: string;
  step?: string;
  reviewRoundId?: string | null;
  bodyVersionId?: string | null;
  plateVersionId?: string | null;
  drawingVersionId?: string | null;
  rawFindings?: number;
  dedupedFindings?: number;
  selectedCandidates?: number;
  expensiveOperations?: number;
  selectionMode?: string | null;
  summary?: Record<string, unknown>;
};

export type ReviewDecisionPayload = {
  decision: ReviewDecisionValue;
  reviewer: string;
  rationale?: string;
  note?: string;
  modifiedText?: string | null;
  modified_text?: string | null;
};

export type VisualAssetMetadata = {
  assetType: string;
  imageUrl: string;
  documentVersionId?: string | null;
  sourceSha256?: string | null;
  physicalPage?: number | null;
  printedIdentifier?: string | null;
  regionId?: string | null;
  bbox?: number[] | null;
  caption?: string | null;
  renderWidth?: number | null;
  renderHeight?: number | null;
  contentType?: string;
};

export type CandidateVisualBundle = {
  candidateId: string;
  source?: VisualAssetMetadata | null;
  canonical?: VisualAssetMetadata | null;
  unresolvedReason?: string | null;
};

export type RetryAnalysisRunResponse = {
  analysisRunId?: string;
  analysis_run_id?: string;
  status: string;
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
  deferredCandidates?: number;
  deferred_candidates?: number;
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

export async function fetchProjects(): Promise<Project[]> {
  const response = await fetch('/api/projects');
  return decode<Project[]>(response);
}

export async function createProject(name: string): Promise<Project> {
  const response = await fetch('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  return decode<Project>(response);
}

export async function fetchReviewRounds(projectId: string): Promise<ReviewRound[]> {
  const response = await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/rounds`);
  const data = await decode<{ items?: ReviewRound[] } | ReviewRound[]>(response);
  if (Array.isArray(data)) return data;
  return data.items ?? [];
}

export async function uploadDocument(
  projectId: string,
  file: File,
  kind: string,
  _legacyStage?: string,
): Promise<UploadAccepted> {
  const body = new FormData();
  body.append('file', file);
  const params = new URLSearchParams({ kind, stage: 'source' });
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/documents?${params.toString()}`,
    { method: 'POST', body },
  );
  return decode<UploadAccepted>(response);
}

export async function getProject(projectId: string): Promise<ProjectDetail> {
  const response = await fetch(`/api/projects/${projectId}`);
  return decode<ProjectDetail>(response);
}

export const fetchProject = getProject;

export async function triggerProofreadingRun(
  projectId: string,
  payload: Partial<RunTriggerPayload> = {},
): Promise<RunTriggerResponse> {
  const reviewRoundId = payload.review_round_id ?? payload.reviewRoundId ?? null;
  if (!reviewRoundId) {
    throw new ApiError('review_round_required');
  }

  const response = await fetch(
    `/api/v1/projects/${encodeURIComponent(projectId)}/runs`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        review_round_id: reviewRoundId,
        enable_vlm: payload.enable_vlm ?? payload.enableVlm ?? true,
        enable_ai_review: payload.enable_ai_review ?? payload.enableAiReview ?? true,
      }),
    },
  );
  return decode<RunTriggerResponse>(response);
}

export async function fetchAnalysisRun(
  projectId: string,
  runId: string,
): Promise<AnalysisRunDiagnostics> {
  const response = await fetch(
    `/api/v1/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}`,
  );
  return decode<AnalysisRunDiagnostics>(response);
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
    `/api/v1/projects/${encodeURIComponent(projectId)}/candidates/${encodeURIComponent(candidateId)}/decisions`,
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

export async function fetchVisualBundle(
  projectId: string,
  candidateId: string,
): Promise<CandidateVisualBundle> {
  const response = await fetch(
    `/api/v1/projects/${encodeURIComponent(projectId)}/candidates/${encodeURIComponent(candidateId)}/visual-bundle`,
  );
  return decode<CandidateVisualBundle>(response);
}

export async function retryAnalysisRun(
  projectId: string,
  analysisRunId: string,
): Promise<RetryAnalysisRunResponse> {
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/analysis-runs/${encodeURIComponent(analysisRunId)}/retry`,
    { method: 'POST' },
  );
  return decode<RetryAnalysisRunResponse>(response);
}

export async function fetchReviewRound(
  projectId: string,
  roundId: string,
): Promise<ReviewRound> {
  const response = await fetch(
    `/api/v1/projects/${encodeURIComponent(projectId)}/rounds/${encodeURIComponent(roundId)}`,
  );
  return decode<ReviewRound>(response);
}

export async function createReviewRound(
  projectId: string,
  payload: CreateReviewRoundPayload,
): Promise<ReviewRound> {
  const bodyVersionId = payload.body_version_id ?? payload.bodyVersionId ?? null;
  if (!bodyVersionId) throw new ApiError('body_version_required');
  const response = await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/rounds`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      body_version_id: bodyVersionId,
      plate_version_id: payload.plate_version_id ?? payload.plateVersionId ?? null,
      drawing_version_id: payload.drawing_version_id ?? payload.drawingVersionId ?? null,
      notes: payload.notes ?? null,
    }),
  });
  return decode<ReviewRound>(response);
}

export async function approveReviewRound(
  projectId: string,
  roundId: string,
): Promise<ReviewRound> {
  const response = await fetch(
    `/api/v1/projects/${encodeURIComponent(projectId)}/rounds/${encodeURIComponent(roundId)}/approve`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    },
  );
  return decode<ReviewRound>(response);
}
