import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  ApiError,
  type CandidateFilters,
  type CandidateVisualBundle,
  type CorrectionCandidate,
  type DocumentVersion,
  type Project,
  type ProjectDetail,
  type ReviewDecision,
  type ReviewMetrics,
  type ReviewRound,
  type RunTriggerResponse,
  type TraceabilityResponse,
  approveReviewRound,
  createReviewRound,
  fetchCandidates,
  fetchMetrics,
  fetchReviewRounds,
  fetchTraceability,
  fetchVisualBundle,
  getProject,
  retryAnalysisRun,
  triggerProofreadingRun,
  uploadDocument,
} from '../api';
import { EvidenceGraphExplorer } from '../components/EvidenceGraphExplorer';
import { SplitViewInspector } from '../components/SplitViewInspector';

type Props = {
  project: Project;
  onBack?: () => void;
};

type TabType = 'split' | 'graph';

const KIND_LABELS: Record<string, string> = {
  report_body: '본문',
  plate_book: '도판 / 사진',
  drawing_book: '도면',
};

const ROUND_STATUS_LABELS: Record<string, string> = {
  draft: '초안',
  reviewing: '검수중',
  revisions_requested: '수정요청',
  approved: '승인됨',
};

function kindLabel(kind: string | undefined): string {
  return kind ? KIND_LABELS[kind] ?? kind : '문서';
}

function roundStatusLabel(status: string): string {
  return ROUND_STATUS_LABELS[status] ?? status;
}

function versionLabel(version: DocumentVersion, kind: string): string {
  return `${kindLabel(kind)} · ${version.originalName}`;
}

function bodyId(round: ReviewRound | null): string | null {
  return round?.bodyVersionId ?? round?.body_version_id ?? null;
}

function plateId(round: ReviewRound | null): string | null {
  return round?.plateVersionId ?? round?.plate_version_id ?? null;
}

function drawingId(round: ReviewRound | null): string | null {
  return round?.drawingVersionId ?? round?.drawing_version_id ?? null;
}

export function ProjectDetailPage({ project, onBack }: Props) {
  const [detail, setDetail] = useState<ProjectDetail>({
    ...project,
    documents: [],
    documentVersions: [],
    analysisRuns: [],
  });
  const [uploading, setUploading] = useState(false);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const pollTimer = useRef<number | null>(null);

  // Uploads create DocumentVersions only. ReviewRound owns revision sequencing.
  const [uploadKind, setUploadKind] = useState('report_body');

  // ReviewRound is the sole authority for a proofreading input set.
  const [rounds, setRounds] = useState<ReviewRound[]>([]);
  const [selectedRoundId, setSelectedRoundId] = useState<string | null>(null);
  const [isCreateRoundOpen, setIsCreateRoundOpen] = useState(false);
  const [newRoundBodyVersionId, setNewRoundBodyVersionId] = useState('');
  const [reusePlate, setReusePlate] = useState(true);
  const [reuseDrawing, setReuseDrawing] = useState(true);
  const [customPlateVersionId, setCustomPlateVersionId] = useState('');
  const [customDrawingVersionId, setCustomDrawingVersionId] = useState('');
  const [roundNotes, setRoundNotes] = useState('');
  const [creatingRound, setCreatingRound] = useState(false);
  const [approvingRound, setApprovingRound] = useState(false);

  const [runningProofread, setRunningProofread] = useState(false);
  const [enableVlm, setEnableVlm] = useState(true);
  const [enableAiReview, setEnableAiReview] = useState(true);
  const [runResult, setRunResult] = useState<RunTriggerResponse | null>(null);
  const [runStatus, setRunStatus] = useState<string | null>(null);

  const [candidates, setCandidates] = useState<CorrectionCandidate[]>([]);
  const [metrics, setMetrics] = useState<ReviewMetrics | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [traceabilityMap, setTraceabilityMap] = useState<Record<string, TraceabilityResponse>>({});
  const [visualBundleMap, setVisualBundleMap] = useState<Record<string, CandidateVisualBundle>>({});
  const [loadingTrace, setLoadingTrace] = useState(false);

  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [filterCategory, setFilterCategory] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [retryingRunId, setRetryingRunId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabType>('split');

  const loadReviewData = useCallback(async () => {
    const filters: CandidateFilters = {};
    if (filterStatus === 'pending_review') filters.status = filterStatus;
    if (filterCategory !== 'all') filters.rule_category = filterCategory;
    const [candRes, metricRes] = await Promise.all([
      fetchCandidates(project.id, filters).catch(() => ({ total: 0, candidates: [] })),
      fetchMetrics(project.id).catch(() => null),
    ]);
    setCandidates(candRes.candidates || []);
    setMetrics(metricRes);
    if (candRes.candidates?.length) {
      setSelectedCandidateId((prev) =>
        prev && candRes.candidates.some((candidate) => candidate.id === prev)
          ? prev
          : candRes.candidates[0].id,
      );
    }
  }, [project.id, filterStatus, filterCategory]);

  const loadProject = useCallback(async () => {
    const next = await getProject(project.id);
    setDetail(next);
    return next;
  }, [project.id]);

  const loadReviewRounds = useCallback(async () => {
    const items = await fetchReviewRounds(project.id);
    setRounds(items);
    setSelectedRoundId((prev) => {
      if (prev && items.some((round) => round.id === prev)) return prev;
      return items.length ? items[items.length - 1].id : null;
    });
  }, [project.id]);

  useEffect(() => {
    void loadReviewData();
  }, [loadReviewData]);

  useEffect(() => {
    let mounted = true;
    getProject(project.id)
      .then((next) => mounted && setDetail(next))
      .catch(() => mounted && setErrorCode('server_error'));
    return () => {
      mounted = false;
    };
  }, [project.id]);

  useEffect(() => {
    void loadReviewRounds().catch(() => {});
  }, [loadReviewRounds]);

  useEffect(() => {
    if (!selectedCandidateId || traceabilityMap[selectedCandidateId]) return;
    let mounted = true;
    setLoadingTrace(true);
    fetchTraceability(project.id, selectedCandidateId)
      .then((trace) => {
        if (mounted) setTraceabilityMap((prev) => ({ ...prev, [selectedCandidateId]: trace }));
      })
      .catch(() => {})
      .finally(() => mounted && setLoadingTrace(false));
    return () => {
      mounted = false;
    };
  }, [project.id, selectedCandidateId, traceabilityMap]);

  useEffect(() => {
    if (!selectedCandidateId || visualBundleMap[selectedCandidateId]) return;
    let mounted = true;
    fetchVisualBundle(project.id, selectedCandidateId)
      .then((bundle) => {
        if (mounted) setVisualBundleMap((prev) => ({ ...prev, [selectedCandidateId]: bundle }));
      })
      .catch(() => {});
    return () => {
      mounted = false;
    };
  }, [project.id, selectedCandidateId, visualBundleMap]);

  useEffect(
    () => () => {
      if (pollTimer.current !== null) window.clearTimeout(pollTimer.current);
    },
    [],
  );

  const refreshLater = useCallback(async () => {
    pollTimer.current = window.setTimeout(async () => {
      try {
        const next = await loadProject();
        if (next.analysisRuns.some((run) => ['queued', 'running'].includes(run.status))) {
          void refreshLater();
        } else {
          void loadReviewData();
        }
      } catch {
        setErrorCode('server_error');
      }
    }, 1200);
  }, [loadProject, loadReviewData]);

  const docKindMap = useMemo(() => {
    const map: Record<string, string> = {};
    for (const doc of detail.documents ?? []) map[doc.id] = doc.kind;
    return map;
  }, [detail.documents]);

  const versionKind = (version: DocumentVersion): string =>
    version.kind ?? docKindMap[version.documentId] ?? 'report_body';

  const bodyVersions = detail.documentVersions.filter((version) => versionKind(version) === 'report_body');
  const plateVersions = detail.documentVersions.filter((version) => versionKind(version) === 'plate_book');
  const drawingVersions = detail.documentVersions.filter((version) => versionKind(version) === 'drawing_book');

  const latestRound = rounds.length ? rounds[rounds.length - 1] : null;
  const selectedRound =
    rounds.find((round) => round.id === selectedRoundId) ?? (rounds.length ? rounds[rounds.length - 1] : null);

  const selectedBodyId = bodyId(selectedRound);
  const selectedPlateId = plateId(selectedRound);
  const selectedDrawingId = drawingId(selectedRound);

  const runForVersion = (versionId: string | null) =>
    versionId ? detail.analysisRuns.find((run) => run.documentVersionId === versionId) : undefined;

  const roundHasCanonicalSet = Boolean(selectedBodyId && selectedPlateId && selectedDrawingId);
  const readinessBlocked =
    !roundHasCanonicalSet ||
    [selectedBodyId, selectedPlateId, selectedDrawingId].some(
      (versionId) => versionId && runForVersion(versionId)?.status === 'failed',
    );

  const pollRunStatus = useCallback(
    async (runId: string) => {
      let attempts = 0;
      const tick = async () => {
        attempts += 1;
        try {
          const next = await loadProject();
          const run = next.analysisRuns.find((item) => item.id === runId);
          if (run) {
            setRunStatus(run.status);
            if (run.status === 'completed' || run.status === 'failed') {
              void loadReviewData();
              return;
            }
          }
        } catch {
          // transient polling failure
        }
        if (attempts < 30) pollTimer.current = window.setTimeout(tick, 2000);
      };
      await tick();
    },
    [loadProject, loadReviewData],
  );

  function openCreateRound() {
    const latestBody = bodyVersions[bodyVersions.length - 1];
    const latestPlate = plateVersions[plateVersions.length - 1];
    const latestDrawing = drawingVersions[drawingVersions.length - 1];
    setNewRoundBodyVersionId(latestBody?.id ?? '');
    setCustomPlateVersionId(latestPlate?.id ?? '');
    setCustomDrawingVersionId(latestDrawing?.id ?? '');
    setReusePlate(Boolean(latestRound));
    setReuseDrawing(Boolean(latestRound));
    setRoundNotes('');
    setIsCreateRoundOpen(true);
  }

  async function handleCreateRound(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreatingRound(true);
    setErrorCode(null);
    try {
      const targetBodyId = newRoundBodyVersionId || bodyVersions[bodyVersions.length - 1]?.id || null;
      const targetPlateId =
        latestRound && reusePlate ? plateId(latestRound) : customPlateVersionId || plateVersions[plateVersions.length - 1]?.id || null;
      const targetDrawingId =
        latestRound && reuseDrawing
          ? drawingId(latestRound)
          : customDrawingVersionId || drawingVersions[drawingVersions.length - 1]?.id || null;

      if (!targetBodyId || !targetPlateId || !targetDrawingId) {
        throw new ApiError('review_round_assets_required');
      }

      const newRound = await createReviewRound(project.id, {
        body_version_id: targetBodyId,
        plate_version_id: targetPlateId,
        drawing_version_id: targetDrawingId,
        notes: roundNotes || null,
      });
      setRounds((prev) => [...prev, newRound]);
      setSelectedRoundId(newRound.id);
      setIsCreateRoundOpen(false);
      setRoundNotes('');
    } catch (error) {
      setErrorCode(error instanceof ApiError ? error.code : error instanceof Error ? error.message : 'server_error');
    } finally {
      setCreatingRound(false);
    }
  }

  async function handleApproveRound(roundId: string) {
    setApprovingRound(true);
    setErrorCode(null);
    try {
      const updated = await approveReviewRound(project.id, roundId);
      setRounds((prev) => prev.map((round) => (round.id === roundId ? { ...round, ...updated } : round)));
    } catch (error) {
      setErrorCode(error instanceof Error ? error.message : 'server_error');
    } finally {
      setApprovingRound(false);
    }
  }

  async function chooseFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = event.target.files;
    if (!files?.length || uploading) return;
    setUploading(true);
    setErrorCode(null);
    try {
      for (const file of Array.from(files)) {
        let kind = uploadKind;
        const lower = file.name.toLowerCase();
        if (lower.includes('도판') || lower.includes('plate')) kind = 'plate_book';
        else if (lower.includes('도면') || lower.includes('drawing')) kind = 'drawing_book';
        else if (lower.includes('본문') || lower.includes('body')) kind = 'report_body';
        await uploadDocument(project.id, file, kind);
      }
      await loadProject();
      void refreshLater();
    } catch (error) {
      setErrorCode(error instanceof ApiError ? error.code : 'server_error');
    } finally {
      setUploading(false);
      event.target.value = '';
    }
  }

  async function handleTriggerProofread() {
    if (!selectedRound) {
      setErrorCode('review_round_required');
      return;
    }
    if (readinessBlocked) {
      setErrorCode(roundHasCanonicalSet ? 'canonical_graph_not_ready' : 'review_round_assets_required');
      return;
    }

    setErrorCode(null);
    setRunningProofread(true);
    setRunStatus('queued');
    try {
      const result = await triggerProofreadingRun(project.id, {
        review_round_id: selectedRound.id,
        enable_vlm: enableVlm,
        enable_ai_review: enableAiReview,
      });
      setRunResult(result);
      setRunStatus(result.status ?? 'queued');
      const runId = result.run_id ?? result.runId;
      if (runId) void pollRunStatus(runId);
    } catch (error) {
      setErrorCode(error instanceof ApiError ? error.code : error instanceof Error ? error.message : 'server_error');
    } finally {
      setRunningProofread(false);
    }
  }

  function handleRunSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void handleTriggerProofread();
  }

  async function handleRetryRun(analysisRunId: string) {
    if (retryingRunId) return;
    setRetryingRunId(analysisRunId);
    setErrorCode(null);
    try {
      await retryAnalysisRun(project.id, analysisRunId);
      void refreshLater();
    } catch (error) {
      setErrorCode(error instanceof Error ? error.message : 'server_error');
    } finally {
      setRetryingRunId(null);
    }
  }

  function handleDecisionSubmitted(newDecision: ReviewDecision) {
    setCandidates((prev) =>
      prev.map((candidate) => {
        if (candidate.id !== newDecision.candidate_id && candidate.id !== newDecision.candidateId) return candidate;
        return {
          ...candidate,
          proposed_text: newDecision.modified_text || candidate.proposed_text || candidate.proposedText,
          decisions: [newDecision, ...(candidate.decisions || [])],
          latest_decision: newDecision,
        };
      }),
    );
    void fetchMetrics(project.id).then(setMetrics).catch(() => {});
    if (selectedCandidateId) {
      void fetchTraceability(project.id, selectedCandidateId)
        .then((trace) => setTraceabilityMap((prev) => ({ ...prev, [selectedCandidateId]: trace })))
        .catch(() => {});
    }
  }

  const filteredCandidates = candidates.filter((candidate) => {
    const latest = candidate.latest_decision ?? candidate.latestDecision ?? null;
    const outcome = latest?.decision_status ?? latest?.decision ?? null;
    if (filterStatus === 'accepted' && outcome !== 'accepted') return false;
    if (filterStatus === 'rejected' && outcome !== 'rejected') return false;
    if (filterStatus === 'modified' && outcome !== 'modified') return false;
    if (filterStatus === 'deferred' && outcome !== 'deferred') return false;
    if (filterStatus === 'pending_review' && outcome !== null) return false;
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return [
      candidate.original_text ?? candidate.originalText ?? '',
      candidate.proposed_text ?? candidate.proposedText ?? '',
      candidate.rule_category ?? candidate.category ?? '',
      candidate.id,
      candidate.archaeology_object_id ?? candidate.archaeologyObjectId ?? '',
    ].some((value) => value.toLowerCase().includes(q));
  });

  const selectedCandidate =
    candidates.find((candidate) => candidate.id === selectedCandidateId) ?? candidates[0] ?? null;
  const selectedTraceability = selectedCandidate ? traceabilityMap[selectedCandidate.id] ?? null : null;
  const selectedVisualBundle = selectedCandidate ? visualBundleMap[selectedCandidate.id] ?? null : null;
  const currentIndex = selectedCandidate
    ? filteredCandidates.findIndex((candidate) => candidate.id === selectedCandidate.id)
    : -1;

  const totalCount = metrics?.total_candidates ?? metrics?.totalCandidates ?? candidates.length;
  const decisionCounts = candidates.reduce(
    (acc, candidate) => {
      const latest = candidate.latest_decision ?? candidate.latestDecision ?? null;
      const outcome = latest?.decision_status ?? latest?.decision ?? null;
      if (outcome === 'accepted') acc.accepted += 1;
      else if (outcome === 'rejected') acc.rejected += 1;
      else if (outcome === 'modified') acc.modified += 1;
      else if (outcome === 'deferred') acc.deferred += 1;
      else acc.pending += 1;
      return acc;
    },
    { pending: 0, accepted: 0, rejected: 0, modified: 0, deferred: 0 },
  );
  const pendingCount = metrics?.pending_candidates ?? metrics?.pendingCandidates ?? decisionCounts.pending;
  const acceptedCount = metrics?.accepted_candidates ?? metrics?.acceptedCandidates ?? decisionCounts.accepted;
  const rejectedCount = metrics?.rejected_candidates ?? metrics?.rejectedCandidates ?? decisionCounts.rejected;
  const completion =
    metrics?.completion_rate ??
    metrics?.completionRate ??
    (totalCount > 0 ? (totalCount - pendingCount) / totalCount : 0);
  const completionRateDisplay = completion <= 1 ? Math.round(completion * 100) : Math.round(completion);

  return (
    <section className="workspace review-workspace" aria-labelledby="project-title">
      <div className="panel project-summary">
        <div>
          {onBack && (
            <button type="button" className="btn-back-link" onClick={onBack} title="프로젝트 목록으로 이동">
              ← 프로젝트 목록으로 돌아가기
            </button>
          )}
          <p className="section-label">현재 프로젝트</p>
          <h2 id="project-title">{project.name}</h2>
          {project.internalCode && <p className="project-code-tag">코드: {project.internalCode}</p>}
        </div>
        <div className="upload-form">
          <div className="upload-field">
            <label htmlFor="upload-kind">문서 종류</label>
            <select
              id="upload-kind"
              value={uploadKind}
              onChange={(event) => setUploadKind(event.target.value)}
              disabled={uploading}
            >
              <option value="report_body">본문</option>
              <option value="plate_book">도판 / 사진</option>
              <option value="drawing_book">도면</option>
            </select>
          </div>
          <div className="upload-field upload-round-hint" aria-label="회차 관리 안내">
            회차 번호와 최종 여부는 파일 업로드가 아니라 검수 라운드에서 자동 관리됩니다.
          </div>
          <label className={`file-button ${uploading ? 'disabled' : ''}`}>
            <span>{uploading ? '업로드 중…' : '원본 PDF 선택'}</span>
            <input
              type="file"
              accept="application/pdf,.pdf"
              aria-label="원본 파일"
              multiple
              onChange={chooseFiles}
              disabled={uploading}
            />
          </label>
        </div>
      </div>

      {errorCode && <p className="error-code">{errorCode}</p>}

      <section className="panel review-rounds-panel" aria-labelledby="rounds-panel-title">
        <div className="panel-header-row">
          <div>
            <p className="section-label">REVIEW ROUND MANAGEMENT</p>
            <h2 id="rounds-panel-title">검수 라운드 관리 및 승인</h2>
          </div>
          <button type="button" className="btn-create-round" onClick={openCreateRound}>
            + 새 검수 라운드 생성
          </button>
        </div>

        {rounds.length === 0 ? (
          <p className="empty-state">
            검수 라운드가 없습니다. 본문·도판/사진·도면을 업로드한 뒤 새 검수 라운드를 생성하세요.
          </p>
        ) : (
          <div className="rounds-container">
            <div className="round-tabs-bar" role="tablist" aria-label="검수 라운드 탭 목록">
              {rounds.map((round) => {
                const isSelected = round.id === selectedRound?.id;
                return (
                  <button
                    key={round.id}
                    type="button"
                    role="tab"
                    aria-selected={isSelected}
                    className={`round-tab-item ${isSelected ? 'active' : ''}`}
                    onClick={() => setSelectedRoundId(round.id)}
                  >
                    <span className="round-tab-sequence">검수 #{round.sequence}</span>
                    <span className={`status-badge status-${round.status}`}>{roundStatusLabel(round.status)}</span>
                  </button>
                );
              })}
            </div>

            {selectedRound && (
              <div className="active-round-card">
                <div className="active-round-header">
                  <div className="round-info-title">
                    <span className="round-badge-large">검수 라운드 #{selectedRound.sequence}</span>
                    <span className={`status status-${selectedRound.status}`}>{roundStatusLabel(selectedRound.status)}</span>
                  </div>
                  <div className="round-actions">
                    {selectedRound.status !== 'approved' ? (
                      <button
                        type="button"
                        className="btn-approve-round"
                        onClick={() => void handleApproveRound(selectedRound.id)}
                        disabled={approvingRound}
                      >
                        {approvingRound ? '승인 처리 중...' : '✓ 검수 라운드 승인'}
                      </button>
                    ) : (
                      <span className="approved-stamp">✓ 승인 완료 (Approved)</span>
                    )}
                  </div>
                </div>
                <div className="active-round-details-grid">
                  <div className="detail-item">
                    <span className="detail-label">본문:</span>
                    <span className="detail-value"><code>{selectedBodyId ?? '미지정'}</code></span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">도판 / 사진:</span>
                    <span className="detail-value"><code>{selectedPlateId ?? '미지정'}</code></span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">도면:</span>
                    <span className="detail-value"><code>{selectedDrawingId ?? '미지정'}</code></span>
                  </div>
                  {selectedRound.notes && (
                    <div className="detail-item full-width">
                      <span className="detail-label">메모:</span>
                      <span className="detail-value">{selectedRound.notes}</span>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {isCreateRoundOpen && (
          <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="create-round-modal-title">
            <div className="modal-card">
              <div className="modal-header">
                <h3 id="create-round-modal-title">새 검수 라운드 생성</h3>
                <button type="button" className="btn-close-modal" onClick={() => setIsCreateRoundOpen(false)}>✕</button>
              </div>
              <form onSubmit={handleCreateRound} className="modal-form">
                <div className="form-field">
                  <label htmlFor="modal-body-version">본문 문서</label>
                  <select
                    id="modal-body-version"
                    value={newRoundBodyVersionId}
                    onChange={(event) => setNewRoundBodyVersionId(event.target.value)}
                  >
                    <option value="">본문 선택</option>
                    {bodyVersions.map((version) => (
                      <option key={version.id} value={version.id}>{versionLabel(version, versionKind(version))}</option>
                    ))}
                  </select>
                </div>

                <div className="asset-reuse-section">
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={Boolean(latestRound) && reusePlate}
                      disabled={!latestRound}
                      onChange={(event) => setReusePlate(event.target.checked)}
                    />
                    <span>이전 라운드 도판 / 사진 재사용</span>
                  </label>
                  {(!latestRound || !reusePlate) && (
                    <div className="form-field sub-field">
                      <label htmlFor="modal-plate-version">도판 / 사진 문서</label>
                      <select
                        id="modal-plate-version"
                        value={customPlateVersionId}
                        onChange={(event) => setCustomPlateVersionId(event.target.value)}
                      >
                        <option value="">도판 / 사진 선택</option>
                        {plateVersions.map((version) => (
                          <option key={version.id} value={version.id}>{versionLabel(version, versionKind(version))}</option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>

                <div className="asset-reuse-section">
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={Boolean(latestRound) && reuseDrawing}
                      disabled={!latestRound}
                      onChange={(event) => setReuseDrawing(event.target.checked)}
                    />
                    <span>이전 라운드 도면 재사용</span>
                  </label>
                  {(!latestRound || !reuseDrawing) && (
                    <div className="form-field sub-field">
                      <label htmlFor="modal-drawing-version">도면 문서</label>
                      <select
                        id="modal-drawing-version"
                        value={customDrawingVersionId}
                        onChange={(event) => setCustomDrawingVersionId(event.target.value)}
                      >
                        <option value="">도면 선택</option>
                        {drawingVersions.map((version) => (
                          <option key={version.id} value={version.id}>{versionLabel(version, versionKind(version))}</option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>

                <div className="form-field">
                  <label htmlFor="modal-round-notes">검수 메모 / 수정 지시사항</label>
                  <textarea
                    id="modal-round-notes"
                    rows={3}
                    value={roundNotes}
                    onChange={(event) => setRoundNotes(event.target.value)}
                    placeholder="예: 수정본 대조 및 도판 번호 교차 재검증"
                  />
                </div>
                <div className="modal-footer">
                  <button type="button" className="btn-cancel" onClick={() => setIsCreateRoundOpen(false)}>취소</button>
                  <button type="submit" className="btn-create-submit" disabled={creatingRound}>
                    {creatingRound ? '생성 중...' : '검수 라운드 생성'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </section>

      <section className="panel proofreading-panel" aria-labelledby="proofread-panel-title">
        <div className="panel-header-row">
          <div>
            <p className="section-label">AI & GRAPH PROOFREADING</p>
            <h2 id="proofread-panel-title">선택한 검수 라운드 분석 실행 및 현황</h2>
          </div>
          <form className="run-form" onSubmit={handleRunSubmit}>
            <div className="run-form-fields">
              <div className="run-field active-run-round" aria-label="실행 대상 검수 라운드">
                {selectedRound ? (
                  <>
                    <strong>검수 #{selectedRound.sequence}</strong>
                    <span>본문 {selectedBodyId}</span>
                    <span>도판/사진 {selectedPlateId}</span>
                    <span>도면 {selectedDrawingId}</span>
                  </>
                ) : (
                  <span>실행할 검수 라운드를 먼저 생성하세요.</span>
                )}
              </div>
              <div className="run-toggles">
                <label className="toggle-label">
                  <input type="checkbox" checked={enableVlm} onChange={(event) => setEnableVlm(event.target.checked)} />
                  <span>VLM 비전 검증</span>
                </label>
                <label className="toggle-label">
                  <input
                    type="checkbox"
                    checked={enableAiReview}
                    onChange={(event) => setEnableAiReview(event.target.checked)}
                  />
                  <span>AI 지능형 심층 분석</span>
                </label>
              </div>
              <button
                type="submit"
                className="btn-trigger-run"
                disabled={runningProofread || !selectedRound || readinessBlocked}
                title={
                  !selectedRound
                    ? '검수 라운드를 먼저 생성하세요.'
                    : !roundHasCanonicalSet
                      ? '본문·도판/사진·도면 3종이 모두 연결된 검수 라운드가 필요합니다.'
                      : readinessBlocked
                        ? '선택한 라운드의 캐노니컬 그래프 수집 실패를 먼저 해결하세요.'
                        : undefined
                }
              >
                {runningProofread ? '교정 분석 실행 중...' : '▶ 선택 라운드 검수 실행'}
              </button>
            </div>
          </form>
        </div>

        {selectedRound && readinessBlocked && (
          <div className="readiness-warning" role="alert">
            <strong>⚠ 검수 준비 상태:</strong>{' '}
            {!roundHasCanonicalSet
              ? '본문·도판/사진·도면 3종이 모두 연결되어야 검수를 실행할 수 있습니다.'
              : '선택한 라운드의 캐노니컬 그래프 수집이 실패했습니다. 해당 파일의 수집을 재시도하세요.'}
          </div>
        )}

        {runResult && (
          <div className="run-result-banner">
            <div className="run-result-head">
              <strong>검수 실행 (Run ID: {runResult.run_id || runResult.runId})</strong>
              <span className={`status status-${runStatus ?? 'queued'}`}>{runStatus ?? 'queued'}</span>
            </div>
            {runResult.warnings?.length ? (
              <ul className="run-warnings">
                {runResult.warnings.map((warning, index) => <li key={index}>{warning}</li>)}
              </ul>
            ) : null}
          </div>
        )}

        {detail.documentVersions.length === 0 ? (
          <p className="empty-state">등록된 원본이 없습니다. 상단에서 본문·도판/사진·도면 PDF를 업로드하세요.</p>
        ) : (
          <div className="run-list">
            {detail.documentVersions.map((version) => {
              const run = detail.analysisRuns.find((candidate) => candidate.documentVersionId === version.id);
              const isRunning = run?.status === 'running';
              const isQueued = run?.status === 'queued';
              const curPage = run?.currentPage;
              const totPage = run?.totalPages;
              const hasPageProgress = curPage !== undefined && curPage !== null && Boolean(totPage && totPage > 0);
              const progressPct = hasPageProgress ? Math.min(100, Math.round((curPage! / totPage!) * 100)) : 0;
              return (
                <article className={`run-card ${isRunning ? 'is-running' : ''}`} key={version.id}>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <strong>{version.originalName}</strong>
                      <span className="version-kind-label">{kindLabel(versionKind(version))}</span>
                      <span>{Math.max(1, Math.ceil(version.sizeBytes / 1024))} KB</span>
                    </div>
                    {isRunning && (
                      <div className="run-progress-box">
                        <div className="run-progress-header">
                          <span className="run-stage-badge">{run.progressStage || '작업 진행 중'}</span>
                          {hasPageProgress && <span>{curPage} / {totPage} 페이지 ({progressPct}%)</span>}
                        </div>
                        {run.progressMessage && <p className="run-progress-msg">{run.progressMessage}</p>}
                        {hasPageProgress && (
                          <div className="run-mini-progress-bar">
                            <div className="run-mini-progress-fill" style={{ width: `${progressPct}%` }} />
                          </div>
                        )}
                      </div>
                    )}
                    <div className="run-stages-track">
                      <span className={`stage-badge ${run?.status === 'completed' || isRunning ? 'active' : ''}`}>파싱</span>
                      <span className="stage-arrow">→</span>
                      <span className={`stage-badge ${run?.status === 'completed' || isRunning ? 'active' : ''}`}>그래프 추출</span>
                      <span className="stage-arrow">→</span>
                      <span className={`stage-badge ${run?.status === 'completed' || isRunning ? 'active' : ''}`}>시각 에셋 대조</span>
                      <span className="stage-arrow">→</span>
                      <span className={`stage-badge ${run?.status === 'completed' ? 'active completed' : ''}`}>완료</span>
                    </div>
                    {isQueued && <div className="run-progress-box">⏳ 대기열에서 작업 순서를 기다리는 중입니다…</div>}
                  </div>
                  <div className="status-column">
                    <span className={`status status-${run?.status ?? 'unknown'}`}>{run?.status ?? 'unknown'}</span>
                    {run?.errorCode && <code>{run.errorCode}</code>}
                    {run?.status === 'failed' && run.retryable && (
                      <button
                        type="button"
                        className="btn-retry"
                        onClick={() => void handleRetryRun(run.id)}
                        disabled={retryingRunId === run.id}
                      >
                        {retryingRunId === run.id ? '재시도 중...' : '재시도'}
                      </button>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      <section className="panel metrics-overview-panel" aria-labelledby="metrics-title">
        <div className="metrics-header-row">
          <div>
            <p className="section-label">REVIEW AUDIT METRICS</p>
            <h2 id="metrics-title">검수 및 감사 진행 통계</h2>
          </div>
          <div className="completion-badge-wrap">
            <span className="completion-label">전체 완료율: {completionRateDisplay}%</span>
            <div className="progress-bar-track">
              <div className="progress-bar-fill" style={{ width: `${Math.min(100, Math.max(0, completionRateDisplay))}%` }} />
            </div>
          </div>
        </div>
        <div className="metrics-cards-grid">
          <div className="metric-card"><span className="metric-title">총 교정 후보</span><span className="metric-number">{totalCount}</span></div>
          <div className="metric-card pending"><span className="metric-title">검수 대기</span><span className="metric-number">{pendingCount}</span></div>
          <div className="metric-card accepted"><span className="metric-title">승인됨</span><span className="metric-number">{acceptedCount}</span></div>
          <div className="metric-card rejected"><span className="metric-title">반려</span><span className="metric-number">{rejectedCount}</span></div>
        </div>
      </section>

      <section className="panel candidate-workspace-panel" aria-labelledby="workspace-title">
        <div className="panel-header-row">
          <div>
            <p className="section-label">EXPERT PROOFREADING WORKSPACE</p>
            <h2 id="workspace-title">고고학 오류 교정 대조 및 판정</h2>
          </div>
          <div className="view-tab-switcher" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'split'}
              className={`tab-btn ${activeTab === 'split' ? 'active' : ''}`}
              onClick={() => setActiveTab('split')}
            >
              분할 뷰 대조 검수 (Split-View)
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'graph'}
              className={`tab-btn ${activeTab === 'graph' ? 'active' : ''}`}
              onClick={() => setActiveTab('graph')}
            >
              근거 지식 그래프 (Evidence Graph)
            </button>
          </div>
        </div>

        <div className="filters-bar">
          <div className="filter-group">
            <label htmlFor="filter-status">상태:</label>
            <select id="filter-status" value={filterStatus} onChange={(event) => setFilterStatus(event.target.value)}>
              <option value="all">전체 상태</option>
              <option value="pending_review">검수 대기</option>
              <option value="accepted">승인 완료</option>
              <option value="rejected">반려</option>
              <option value="modified">수정 승인</option>
              <option value="deferred">보류</option>
            </select>
          </div>
          <div className="filter-group">
            <label htmlFor="filter-category">유형:</label>
            <select id="filter-category" value={filterCategory} onChange={(event) => setFilterCategory(event.target.value)}>
              <option value="all">전체 유형</option>
              <option value="figure_plate_table_photo_ref">도판/사진 참조</option>
              <option value="annotation_resolution">주석/참조 해석</option>
              <option value="feature_or_artifact_id">유구/유물 식별</option>
              <option value="numeric_value">수치/단위</option>
              <option value="site_or_area_name">지점/구역 명칭</option>
              <option value="direction_period_term">방향/시대 용어</option>
            </select>
          </div>
          <div className="filter-group search-group">
            <label htmlFor="candidate-search">검색:</label>
            <input
              id="candidate-search"
              type="text"
              placeholder="본문 텍스트, 도판 ID, 후보 ID 검색..."
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
            />
          </div>
        </div>

        {filteredCandidates.length === 0 ? (
          <div className="empty-state-box">
            <p>조건에 일치하는 교정 후보가 없습니다.</p>
            {candidates.length === 0 && <p className="muted">검수 라운드를 선택하고 [선택 라운드 검수 실행]을 눌러 분석하세요.</p>}
          </div>
        ) : (
          <div className="inspector-workspace-grid">
            <aside className="candidate-sidebar" aria-label="교정 후보 목록">
              <div className="sidebar-header"><span>교정 후보 목록 ({filteredCandidates.length}건)</span></div>
              <div className="candidate-card-list">
                {filteredCandidates.map((candidate, index) => {
                  const isSelected = candidate.id === selectedCandidate?.id;
                  const original = candidate.original_text ?? candidate.originalText ?? '';
                  const proposed = candidate.proposed_text ?? candidate.proposedText ?? '';
                  const category = candidate.rule_category ?? candidate.category ?? '일반';
                  return (
                    <div
                      key={candidate.id}
                      className={`candidate-list-card ${isSelected ? 'selected' : ''}`}
                      onClick={() => setSelectedCandidateId(candidate.id)}
                      role="button"
                      tabIndex={0}
                    >
                      <div className="cand-card-top">
                        <span className="cand-index">#{index + 1}</span>
                        <span className="cand-cat">{category}</span>
                        {candidate.archaeology_object_id && <span className="cand-obj-id">{candidate.archaeology_object_id}</span>}
                      </div>
                      <div className="cand-card-body">
                        <div className="cand-snippet-orig"><strong>원본:</strong> {original || '(텍스트 없음)'}</div>
                        {proposed && <div className="cand-snippet-prop"><strong>제안:</strong> {proposed}</div>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </aside>
            <main className="inspector-main-panel">
              <div className="quick-nav-bar">
                <button
                  type="button"
                  className="btn-nav"
                  disabled={currentIndex <= 0}
                  onClick={() => currentIndex > 0 && setSelectedCandidateId(filteredCandidates[currentIndex - 1].id)}
                >
                  ◀ 이전 후보
                </button>
                <span className="nav-position-label">후보 {currentIndex + 1} / {filteredCandidates.length}</span>
                <button
                  type="button"
                  className="btn-nav"
                  disabled={currentIndex >= filteredCandidates.length - 1}
                  onClick={() =>
                    currentIndex < filteredCandidates.length - 1 && setSelectedCandidateId(filteredCandidates[currentIndex + 1].id)
                  }
                >
                  다음 후보 ▶
                </button>
              </div>
              {selectedCandidate && activeTab === 'split' && (
                <SplitViewInspector
                  projectId={project.id}
                  candidate={selectedCandidate}
                  traceability={selectedTraceability}
                  visualBundle={selectedVisualBundle}
                  onDecisionSubmitted={handleDecisionSubmitted}
                />
              )}
              {selectedCandidate && activeTab === 'graph' && (
                <EvidenceGraphExplorer
                  candidate={selectedCandidate}
                  traceability={selectedTraceability}
                  visualBundle={selectedVisualBundle}
                  loading={loadingTrace}
                />
              )}
            </main>
          </div>
        )}
      </section>
    </section>
  );
}
