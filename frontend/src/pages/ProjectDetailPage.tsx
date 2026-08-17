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
  type RunTriggerResponse,
  type TraceabilityResponse,
  fetchCandidates,
  fetchMetrics,
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
  plate_book: '도판',
  drawing_book: '도면',
};

const STAGE_LABELS: Record<string, string> = {
  '1차': '1차',
  '2차': '2차',
  '3차': '3차',
  final: '최종',
};

function kindLabel(kind: string | undefined): string {
  return kind ? KIND_LABELS[kind] ?? kind : '문서';
}

function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

function versionLabel(version: DocumentVersion, kind: string): string {
  return `${kindLabel(kind)} · ${stageLabel(version.stage)}`;
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

  // Upload form state
  const [uploadKind, setUploadKind] = useState('report_body');
  const [uploadStage, setUploadStage] = useState('1차');

  // Proofreading & Candidates State
  const [runningProofread, setRunningProofread] = useState(false);
  const [enableVlm, setEnableVlm] = useState(true);
  const [enableAiReview, setEnableAiReview] = useState(true);
  const [bodyVersionId, setBodyVersionId] = useState('');
  const [plateVersionId, setPlateVersionId] = useState('');
  const [drawingVersionId, setDrawingVersionId] = useState('');
  const [runResult, setRunResult] = useState<RunTriggerResponse | null>(null);
  const [runStatus, setRunStatus] = useState<string | null>(null);

  // Candidates & Metrics
  const [candidates, setCandidates] = useState<CorrectionCandidate[]>([]);
  const [metrics, setMetrics] = useState<ReviewMetrics | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [traceabilityMap, setTraceabilityMap] = useState<Record<string, TraceabilityResponse>>({});
  const [visualBundleMap, setVisualBundleMap] = useState<Record<string, CandidateVisualBundle>>({});
  const [loadingTrace, setLoadingTrace] = useState(false);

  // Filters
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [filterCategory, setFilterCategory] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Retry state
  const [retryingRunId, setRetryingRunId] = useState<string | null>(null);

  // Active View Tab for Inspector
  const [activeTab, setActiveTab] = useState<TabType>('split');

  // Load project details, candidates, and metrics
  const loadReviewData = useCallback(async () => {
    try {
      const filters: CandidateFilters = {};
      if (filterStatus === 'pending_review') filters.status = filterStatus;
      if (filterCategory !== 'all') filters.rule_category = filterCategory;

      const [candRes, metricRes] = await Promise.all([
        fetchCandidates(project.id, filters).catch(() => ({ total: 0, candidates: [] })),
        fetchMetrics(project.id).catch(() => null),
      ]);

      setCandidates(candRes.candidates || []);
      setMetrics(metricRes);

      if (candRes.candidates && candRes.candidates.length > 0) {
        setSelectedCandidateId((prev) =>
          prev && candRes.candidates.some((c) => c.id === prev)
            ? prev
            : candRes.candidates[0].id,
        );
      }
    } catch {
      // Non-critical data loading error
    }
  }, [project.id, filterStatus, filterCategory]);

  useEffect(() => {
    void loadReviewData();
  }, [loadReviewData]);

  useEffect(() => {
    let isMounted = true;
    getProject(project.id)
      .then((next) => {
        if (isMounted) setDetail(next);
      })
      .catch(() => {
        if (isMounted) setErrorCode('server_error');
      });
    return () => {
      isMounted = false;
    };
  }, [project.id]);

  // When selected candidate changes, fetch its traceability if not yet cached
  useEffect(() => {
    if (!selectedCandidateId) return;
    if (traceabilityMap[selectedCandidateId]) return;

    let isMounted = true;
    setLoadingTrace(true);
    fetchTraceability(project.id, selectedCandidateId)
      .then((trace) => {
        if (isMounted) {
          setTraceabilityMap((prev) => ({ ...prev, [selectedCandidateId]: trace }));
        }
      })
      .catch(() => {
        // Fallback gracefully
      })
      .finally(() => {
        if (isMounted) setLoadingTrace(false);
      });

    return () => {
      isMounted = false;
    };
  }, [project.id, selectedCandidateId, traceabilityMap]);

  // Fetch the visual bundle (Test D) for the selected candidate so both the
  // split view and the evidence graph can render the real source material.
  useEffect(() => {
    if (!selectedCandidateId) return;
    if (visualBundleMap[selectedCandidateId]) return;

    let isMounted = true;
    fetchVisualBundle(project.id, selectedCandidateId)
      .then((bundle) => {
        if (isMounted) {
          setVisualBundleMap((prev) => ({ ...prev, [selectedCandidateId]: bundle }));
        }
      })
      .catch(() => {
        // Visual assets are optional; the split view shows a graceful fallback.
      });

    return () => {
      isMounted = false;
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
        const next = await getProject(project.id);
        setDetail(next);
        if (next.analysisRuns.some((run) => ['queued', 'running'].includes(run.status))) {
          void refreshLater();
        } else {
          void loadReviewData();
        }
      } catch {
        setErrorCode('server_error');
      }
    }, 1200);
  }, [project.id, loadReviewData]);

  const docKindMap = useMemo(() => {
    const map: Record<string, string> = {};
    for (const doc of detail.documents ?? []) map[doc.id] = doc.kind;
    return map;
  }, [detail.documents]);

  const versionKind = (version: DocumentVersion): string =>
    version.kind ?? docKindMap[version.documentId] ?? 'report_body';

  const bodyVersions = detail.documentVersions.filter(
    (v) => versionKind(v) === 'report_body',
  );
  const plateVersions = detail.documentVersions.filter((v) => versionKind(v) === 'plate_book');
  const drawingVersions = detail.documentVersions.filter((v) => versionKind(v) === 'drawing_book');

  useEffect(() => {
    if (!bodyVersionId && bodyVersions.length > 0) {
      setBodyVersionId(bodyVersions[0].id);
    }
  }, [bodyVersions, bodyVersionId]);

  // Analysis readiness (§8.2): disable 검수 시작 when a selected version's
  // canonical graph ingestion failed.
  const runForVersion = (versionId: string) =>
    detail.analysisRuns.find((r) => r.documentVersionId === versionId);
  const bodyIngestFailed = bodyVersionId
    ? runForVersion(bodyVersionId)?.status === 'failed'
    : false;
  const plateIngestFailed = plateVersionId
    ? runForVersion(plateVersionId)?.status === 'failed'
    : false;
  const drawingIngestFailed = drawingVersionId
    ? runForVersion(drawingVersionId)?.status === 'failed'
    : false;
  const readinessBlocked = bodyIngestFailed || plateIngestFailed || drawingIngestFailed;

  const pollRunStatus = useCallback(
    async (runId: string) => {
      let attempts = 0;
      const maxAttempts = 30;
      const tick = async () => {
        attempts += 1;
        try {
          const next = await getProject(project.id);
          setDetail(next);
          const run = next.analysisRuns.find((r) => r.id === runId);
          if (run) {
            setRunStatus(run.status);
            if (run.status === 'completed' || run.status === 'failed') {
              void loadReviewData();
              return;
            }
          }
        } catch {
          // transient failure; keep polling
        }
        if (attempts < maxAttempts) {
          pollTimer.current = window.setTimeout(tick, 2000);
        }
      };
      await tick();
    },
    [project.id, loadReviewData],
  );

  async function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || uploading) return;

    setUploading(true);
    setErrorCode(null);
    try {
      const accepted = await uploadDocument(project.id, file, uploadKind, uploadStage);
      setDetail((current) => ({
        ...current,
        documentVersions: [
          ...current.documentVersions,
          {
            id: accepted.documentVersionId,
            documentId: accepted.documentVersionId,
            originalName: file.name,
            mimeType: file.type || 'application/octet-stream',
            sizeBytes: file.size,
            stage: uploadStage,
            kind: uploadKind,
          },
        ],
        analysisRuns: [
          ...current.analysisRuns,
          {
            id: accepted.analysisRunId,
            status: 'queued',
            step: 'ingest',
            documentVersionId: accepted.documentVersionId,
            errorCode: null,
            retryable: false,
          },
        ],
      }));
      void refreshLater();
    } catch (error) {
      setErrorCode(error instanceof ApiError ? error.code : 'server_error');
    } finally {
      setUploading(false);
      event.target.value = '';
    }
  }

  async function handleTriggerProofread() {
    if (!bodyVersionId) return;
    setErrorCode(null);
    setRunningProofread(true);
    setRunStatus('queued');
    const selectedBody = bodyVersions.find((v) => v.id === bodyVersionId);
    try {
      const res = await triggerProofreadingRun(project.id, {
        body_version_id: bodyVersionId,
        plate_version_id: plateVersionId || null,
        drawing_version_id: drawingVersionId || null,
        enable_vlm: enableVlm,
        enable_ai_review: enableAiReview,
        version_stage: selectedBody?.stage ?? '1차',
      });
      setRunResult(res);
      setRunStatus(res.status ?? 'queued');
      const runId = res.run_id ?? res.runId;
      if (runId) {
        void pollRunStatus(runId);
      }
    } catch (err) {
      setErrorCode(err instanceof Error ? err.message : '교정 분석 실행 중 오류가 발생했습니다.');
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
    } catch (err) {
      setErrorCode(err instanceof Error ? err.message : '재시도 요청 중 오류가 발생했습니다.');
    } finally {
      setRetryingRunId(null);
    }
  }

  function handleDecisionSubmitted(newDecision: ReviewDecision) {
    setCandidates((prev) =>
      prev.map((c) => {
        if (c.id === newDecision.candidate_id || c.id === newDecision.candidateId) {
          return {
            ...c,
            proposed_text: newDecision.modified_text || c.proposed_text || c.proposedText,
            decisions: [newDecision, ...(c.decisions || [])],
            latest_decision: newDecision,
          };
        }
        return c;
      }),
    );

    // Refresh metrics & traceability cache
    void fetchMetrics(project.id).then((m) => setMetrics(m)).catch(() => {});
    if (selectedCandidateId) {
      void fetchTraceability(project.id, selectedCandidateId).then((t) => {
        setTraceabilityMap((prev) => ({ ...prev, [selectedCandidateId]: t }));
      }).catch(() => {});
    }
  }

  // Filter candidates by search query
  const filteredCandidates = candidates.filter((c) => {
    const latest =
      c.latest_decision ?? c.latestDecision ?? null;
    const outcome = latest?.decision_status ?? latest?.decision ?? null;
    if (filterStatus === 'accepted' && outcome !== 'accepted') return false;
    if (filterStatus === 'rejected' && outcome !== 'rejected') return false;
    if (filterStatus === 'modified' && outcome !== 'modified') return false;
    if (filterStatus === 'deferred' && outcome !== 'deferred') return false;
    if (filterStatus === 'pending_review' && outcome !== null) return false;
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    const orig = (c.original_text || c.originalText || '').toLowerCase();
    const prop = (c.proposed_text || c.proposedText || '').toLowerCase();
    const cat = (c.rule_category || c.category || '').toLowerCase();
    const id = c.id.toLowerCase();
    const objId = (c.archaeology_object_id || c.archaeologyObjectId || '').toLowerCase();
    return orig.includes(q) || prop.includes(q) || cat.includes(q) || id.includes(q) || objId.includes(q);
  });

  const selectedCandidate =
    candidates.find((c) => c.id === selectedCandidateId) ||
    (candidates.length > 0 ? candidates[0] : null);

  const selectedTraceability = selectedCandidate
    ? traceabilityMap[selectedCandidate.id] || null
    : null;

  const selectedVisualBundle = selectedCandidate
    ? visualBundleMap[selectedCandidate.id] || null
    : null;

  // Selected candidate index for prev/next buttons
  const currentIndex = selectedCandidate
    ? filteredCandidates.findIndex((c) => c.id === selectedCandidate.id)
    : -1;

  // Metrics computation helpers
  const totalCount = metrics?.total_candidates ?? metrics?.totalCandidates ?? candidates.length;
  const decisionCounts = candidates.reduce(
    (acc, c) => {
      const latest = c.latest_decision ?? c.latestDecision ?? null;
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
  const pendingCount =
    metrics?.pending_candidates ?? metrics?.pendingCandidates ?? decisionCounts.pending;
  const acceptedCount =
    metrics?.accepted_candidates ?? metrics?.acceptedCandidates ?? decisionCounts.accepted;
  const rejectedCount =
    metrics?.rejected_candidates ?? metrics?.rejectedCandidates ?? decisionCounts.rejected;
  const completionRate =
    metrics?.completion_rate ??
    metrics?.completionRate ??
    (totalCount > 0 ? Math.round(((totalCount - pendingCount) / totalCount) * 100) : 0);
  const completionRateDisplay =
    typeof completionRate === 'number'
      ? completionRate <= 1
        ? Math.round(completionRate * 100)
        : Math.round(completionRate)
      : 0;

  return (
    <section className="workspace review-workspace" aria-labelledby="project-title">
      {/* Top Project Summary Bar */}
      <div className="panel project-summary">
        <div>
          {onBack && (
            <button
              type="button"
              className="btn-back-link"
              onClick={onBack}
              title="프로젝트 목록으로 이동"
            >
              ← 프로젝트 목록으로 돌아가기
            </button>
          )}
          <p className="section-label">현재 프로젝트</p>
          <h2 id="project-title">{project.name}</h2>
          {project.internalCode && (
            <p className="project-code-tag">코드: {project.internalCode}</p>
          )}
        </div>
        <div className="upload-form">
          <div className="upload-field">
            <label htmlFor="upload-kind">문서 종류</label>
            <select
              id="upload-kind"
              value={uploadKind}
              onChange={(e) => setUploadKind(e.target.value)}
              disabled={uploading}
            >
              <option value="report_body">본문</option>
              <option value="plate_book">도판</option>
              <option value="drawing_book">도면</option>
            </select>
          </div>
          <div className="upload-field">
            <label htmlFor="upload-stage">교정 단계</label>
            <select
              id="upload-stage"
              value={uploadStage}
              onChange={(e) => setUploadStage(e.target.value)}
              disabled={uploading}
            >
              <option value="1차">1차</option>
              <option value="2차">2차</option>
              <option value="3차">3차</option>
              <option value="final">최종</option>
            </select>
          </div>
          <label className={`file-button ${uploading ? 'disabled' : ''}`}>
            <span>{uploading ? '업로드 중…' : '원본 PDF 선택'}</span>
            <input
              type="file"
              accept="application/pdf,.pdf"
              aria-label="원본 파일"
              onChange={chooseFile}
              disabled={uploading}
            />
          </label>
        </div>
      </div>

      {errorCode && <p className="error-code">{errorCode}</p>}

      {/* Analysis Runs & Proofreading Trigger Panel */}
      <section className="panel proofreading-panel" aria-labelledby="proofread-panel-title">
        <div className="panel-header-row">
          <div>
            <p className="section-label">AI & GRAPH PROOFREADING</p>
            <h2 id="proofread-panel-title">보고서 교정 분석 실행 및 현황</h2>
          </div>
          <form className="run-form" onSubmit={handleRunSubmit}>
            <div className="run-form-fields">
              <div className="run-field">
                <label htmlFor="run-body-version">본문 버전</label>
                <select
                  id="run-body-version"
                  value={bodyVersionId}
                  onChange={(e) => setBodyVersionId(e.target.value)}
                  aria-label="본문 버전"
                >
                  {bodyVersions.length === 0 && <option value="">본문 버전 없음</option>}
                  {bodyVersions.map((v) => (
                    <option key={v.id} value={v.id}>
                      {versionLabel(v, versionKind(v))}
                    </option>
                  ))}
                </select>
              </div>
              <div className="run-field">
                <label htmlFor="run-plate-version">도판 버전 (선택)</label>
                <select
                  id="run-plate-version"
                  value={plateVersionId}
                  onChange={(e) => setPlateVersionId(e.target.value)}
                  aria-label="도판 버전"
                >
                  <option value="">선택 안 함</option>
                  {plateVersions.map((v) => (
                    <option key={v.id} value={v.id}>
                      {versionLabel(v, versionKind(v))}
                    </option>
                  ))}
                </select>
              </div>
              <div className="run-field">
                <label htmlFor="run-drawing-version">도면 버전 (선택)</label>
                <select
                  id="run-drawing-version"
                  value={drawingVersionId}
                  onChange={(e) => setDrawingVersionId(e.target.value)}
                  aria-label="도면 버전"
                >
                  <option value="">선택 안 함</option>
                  {drawingVersions.map((v) => (
                    <option key={v.id} value={v.id}>
                      {versionLabel(v, versionKind(v))}
                    </option>
                  ))}
                </select>
              </div>
              <div className="run-toggles">
                <label className="toggle-label">
                  <input
                    type="checkbox"
                    checked={enableVlm}
                    onChange={(e) => setEnableVlm(e.target.checked)}
                  />
                  <span>VLM 비전 검증</span>
                </label>
                <label className="toggle-label">
                  <input
                    type="checkbox"
                    checked={enableAiReview}
                    onChange={(e) => setEnableAiReview(e.target.checked)}
                  />
                  <span>AI 지능형 심층 분석</span>
                </label>
              </div>
              <button
                type="submit"
                className="btn-trigger-run"
                disabled={runningProofread || !bodyVersionId || readinessBlocked}
                title={
                  readinessBlocked
                    ? '선택한 버전의 캐노니컬 그래프 수집이 실패하여 검수를 시작할 수 없습니다.'
                    : undefined
                }
              >
                {runningProofread ? '교정 분석 실행 중...' : '▶ 새 검수 실행'}
              </button>
            </div>
          </form>
        </div>

        {readinessBlocked && (
          <div className="readiness-warning" role="alert">
            <strong>⚠ 검수 준비 상태:</strong> 선택한 버전 중 캐노니컬 그래프 수집이 실패한
            버전이 있어 [새 검수 실행]이 비활성화되었습니다. 실패한 수집을 [재시도]한 뒤 다시
            시도하세요.
          </div>
        )}

        {runResult && (
          <div className="run-result-banner">
            <div className="run-result-head">
              <strong>검수 실행 (Run ID: {runResult.run_id || runResult.runId})</strong>
              <span className={`status status-${runStatus ?? 'queued'}`}>
                {runStatus ?? 'queued'}
              </span>
            </div>
            {runResult.warnings && runResult.warnings.length > 0 && (
              <ul className="run-warnings">
                {runResult.warnings.map((warning, idx) => (
                  <li key={idx}>{warning}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {/* Existing Runs List */}
        {detail.documentVersions.length === 0 ? (
          <p className="empty-state">등록된 원본이 없습니다. 상단에서 원본 PDF를 업로드하세요.</p>
        ) : (
          <div className="run-list">
            {detail.documentVersions.map((version) => {
              const run = detail.analysisRuns.find(
                (candidate) => candidate.documentVersionId === version.id,
              );
              const isRunning = run?.status === 'running';
              const isQueued = run?.status === 'queued';
              const curPage = run?.currentPage;
              const totPage = run?.totalPages;
              const hasPageProgress = curPage !== undefined && curPage !== null && totPage && totPage > 0;
              const progressPct = hasPageProgress ? Math.min(100, Math.round((curPage / totPage) * 100)) : 0;

              return (
                <article className={`run-card ${isRunning ? 'is-running' : ''}`} key={version.id}>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <strong>{version.originalName}</strong>
                      <span className="version-kind-label">{versionLabel(version, versionKind(version))}</span>
                      <span>{Math.max(1, Math.ceil(version.sizeBytes / 1024))} KB</span>
                    </div>

                    {/* Real-time Ingest / Analysis Progress */}
                    {isRunning && (
                      <div className="run-progress-box">
                        <div className="run-progress-header">
                          <span className="run-stage-badge">
                            {run.progressStage || '작업 진행 중'}
                          </span>
                          {hasPageProgress && (
                            <span style={{ fontSize: '0.78rem', color: '#1e5c41', fontWeight: 600 }}>
                              {curPage} / {totPage} 페이지 ({progressPct}%)
                            </span>
                          )}
                        </div>
                        {run.progressMessage && (
                          <p className="run-progress-msg">{run.progressMessage}</p>
                        )}
                        {hasPageProgress && (
                          <div className="run-mini-progress-bar">
                            <div
                              className="run-mini-progress-fill"
                              style={{ width: `${progressPct}%` }}
                            />
                          </div>
                        )}
                      </div>
                    )}

                    {isQueued && (
                      <div className="run-progress-box" style={{ background: '#fdfaf5', borderColor: '#e0d6c4' }}>
                        <span style={{ fontSize: '0.8rem', color: '#886d38', fontWeight: 600 }}>
                          ⏳ 대기열에서 작업 순서를 기다리는 중입니다…
                        </span>
                      </div>
                    )}
                  </div>
                  <div className="status-column">
                    <span className={`status status-${run?.status ?? 'unknown'}`}>
                      {run?.status === 'running' ? '실행 중' : run?.status === 'queued' ? '대기 중' : run?.status === 'completed' ? '완료' : run?.status === 'failed' ? '실패' : run?.status ?? 'unknown'}
                    </span>
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

      {/* METRICS OVERVIEW BAR */}
      <section className="panel metrics-overview-panel" aria-labelledby="metrics-title">
        <div className="metrics-header-row">
          <div>
            <p className="section-label">REVIEW AUDIT METRICS</p>
            <h2 id="metrics-title">검수 및 감사 진행 통계</h2>
          </div>
          <div className="completion-badge-wrap">
            <span className="completion-label">전체 완료율: {completionRateDisplay}%</span>
            <div className="progress-bar-track">
              <div
                className="progress-bar-fill"
                style={{ width: `${Math.min(100, Math.max(0, completionRateDisplay))}%` }}
              />
            </div>
          </div>
        </div>

        <div className="metrics-cards-grid">
          <div className="metric-card">
            <span className="metric-title">총 교정 후보</span>
            <span className="metric-number">{totalCount}</span>
          </div>
          <div className="metric-card pending">
            <span className="metric-title">검수 대기</span>
            <span className="metric-number">{pendingCount}</span>
          </div>
          <div className="metric-card accepted">
            <span className="metric-title">승인됨</span>
            <span className="metric-number">{acceptedCount}</span>
          </div>
          <div className="metric-card rejected">
            <span className="metric-title">반려 / 노이즈</span>
            <span className="metric-number">{rejectedCount}</span>
          </div>
        </div>
      </section>

      {/* CANDIDATE INSPECTOR WORKSPACE */}
      <section className="panel candidate-workspace-panel" aria-labelledby="workspace-title">
        <div className="panel-header-row">
          <div>
            <p className="section-label">EXPERT PROOFREADING WORKSPACE</p>
            <h2 id="workspace-title">고고학 오류 교정 대조 및 판정</h2>
          </div>
          {/* Tab Switcher */}
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

        {/* Filter Controls Bar */}
        <div className="filters-bar">
          <div className="filter-group">
            <label htmlFor="filter-status">상태:</label>
            <select
              id="filter-status"
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
            >
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
            <select
              id="filter-category"
              value={filterCategory}
              onChange={(e) => setFilterCategory(e.target.value)}
            >
              <option value="all">전체 유형</option>
              <option value="plate_reference">도판 번호 불일치</option>
              <option value="drawing_reference">도면 참조 오류</option>
              <option value="dimension_unit">단위/치수 오류</option>
              <option value="typo">오탈자</option>
            </select>
          </div>

          <div className="filter-group search-group">
            <label htmlFor="candidate-search">검색:</label>
            <input
              id="candidate-search"
              type="text"
              placeholder="본문 텍스트, 도판 ID, 후보 ID 검색..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </div>

        {/* Workspace Main Area: Candidate List (Sidebar) + Active Inspector (Main) */}
        {filteredCandidates.length === 0 ? (
          <div className="empty-state-box">
            <p>조건에 일치하는 교정 후보가 없습니다.</p>
            {candidates.length === 0 && (
              <p className="muted">
                상단의 <strong>[새 검수 실행]</strong> 버튼을 눌러 PDF 원본을 분석하세요.
              </p>
            )}
          </div>
        ) : (
          <div className="inspector-workspace-grid">
            {/* Candidate Selector List */}
            <aside className="candidate-sidebar" aria-label="교정 후보 목록">
              <div className="sidebar-header">
                <span>교정 후보 목록 ({filteredCandidates.length}건)</span>
              </div>
              <div className="candidate-card-list">
                {filteredCandidates.map((cand, idx) => {
                  const isSelected = cand.id === selectedCandidate?.id;
                  const orig = cand.original_text ?? cand.originalText ?? '';
                  const prop = cand.proposed_text ?? cand.proposedText ?? '';
                  const cat = cand.rule_category ?? cand.category ?? '일반';
                  const stat = cand.status ?? 'pending_review';

                  return (
                    <div
                      key={cand.id}
                      className={`candidate-list-card ${isSelected ? 'selected' : ''}`}
                      onClick={() => setSelectedCandidateId(cand.id)}
                      role="button"
                      tabIndex={0}
                    >
                      <div className="cand-card-top">
                        <span className="cand-index">#{idx + 1}</span>
                        <span className={`cand-status-dot status-dot-${stat}`} />
                        <span className="cand-cat">{cat}</span>
                        {cand.archaeology_object_id && (
                          <span className="cand-obj-id">{cand.archaeology_object_id}</span>
                        )}
                      </div>
                      <div className="cand-card-body">
                        <div className="cand-snippet-orig">
                          <strong>원본:</strong> {orig || '(텍스트 없음)'}
                        </div>
                        {prop && (
                          <div className="cand-snippet-prop">
                            <strong>제안:</strong> {prop}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </aside>

            {/* Active Inspector / Graph Area */}
            <main className="inspector-main-panel">
              {/* Prev / Next Candidate Quick Nav */}
              <div className="quick-nav-bar">
                <button
                  type="button"
                  className="btn-nav"
                  disabled={currentIndex <= 0}
                  onClick={() => {
                    if (currentIndex > 0) {
                      setSelectedCandidateId(filteredCandidates[currentIndex - 1].id);
                    }
                  }}
                >
                  ◀ 이전 후보
                </button>
                <span className="nav-position-label">
                  후보 {currentIndex + 1} / {filteredCandidates.length}
                </span>
                <button
                  type="button"
                  className="btn-nav"
                  disabled={currentIndex >= filteredCandidates.length - 1}
                  onClick={() => {
                    if (currentIndex < filteredCandidates.length - 1) {
                      setSelectedCandidateId(filteredCandidates[currentIndex + 1].id);
                    }
                  }}
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
