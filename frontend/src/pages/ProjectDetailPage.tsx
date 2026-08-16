import { ChangeEvent, useCallback, useEffect, useRef, useState } from 'react';

import {
  ApiError,
  type CandidateFilters,
  type CorrectionCandidate,
  type Project,
  type ProjectDetail,
  type ReviewDecision,
  type ReviewMetrics,
  type RunTriggerResponse,
  type TraceabilityResponse,
  fetchCandidates,
  fetchMetrics,
  fetchTraceability,
  getProject,
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

export function ProjectDetailPage({ project, onBack }: Props) {
  const [detail, setDetail] = useState<ProjectDetail>({
    ...project,
    documentVersions: [],
    analysisRuns: [],
  });
  const [uploading, setUploading] = useState(false);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const pollTimer = useRef<number | null>(null);

  // Proofreading & Candidates State
  const [runningProofread, setRunningProofread] = useState(false);
  const [enableVlm, setEnableVlm] = useState(true);
  const [enableAiReview, setEnableAiReview] = useState(true);
  const [versionStage, setVersionStage] = useState('1차');
  const [runResult, setRunResult] = useState<RunTriggerResponse | null>(null);

  // Candidates & Metrics
  const [candidates, setCandidates] = useState<CorrectionCandidate[]>([]);
  const [metrics, setMetrics] = useState<ReviewMetrics | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [traceabilityMap, setTraceabilityMap] = useState<Record<string, TraceabilityResponse>>({});
  const [loadingTrace, setLoadingTrace] = useState(false);

  // Filters
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [filterSeverity, setFilterSeverity] = useState<string>('all');
  const [filterCategory, setFilterCategory] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Active View Tab for Inspector
  const [activeTab, setActiveTab] = useState<TabType>('split');

  // Load project details, candidates, and metrics
  const loadReviewData = useCallback(async () => {
    try {
      const filters: CandidateFilters = {};
      if (filterStatus !== 'all') filters.status = filterStatus;
      if (filterSeverity !== 'all') filters.severity = filterSeverity;
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
  }, [project.id, filterStatus, filterSeverity, filterCategory]);

  useEffect(() => {
    void loadReviewData();
  }, [loadReviewData]);

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
    }, 2000);
  }, [project.id, loadReviewData]);

  async function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || uploading) return;

    setUploading(true);
    setErrorCode(null);
    try {
      const accepted = await uploadDocument(project.id, file);
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
            stage: 'source',
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
    setErrorCode(null);
    setRunningProofread(true);
    try {
      const res = await triggerProofreadingRun(project.id, {
        enable_vlm: enableVlm,
        enable_ai_review: enableAiReview,
        version_stage: versionStage,
      });
      setRunResult(res);
      await loadReviewData();
    } catch (err) {
      setErrorCode(err instanceof Error ? err.message : '교정 분석 실행 중 오류가 발생했습니다.');
    } finally {
      setRunningProofread(false);
    }
  }

  function handleDecisionSubmitted(newDecision: ReviewDecision) {
    // Update local candidate list
    setCandidates((prev) =>
      prev.map((c) => {
        if (c.id === newDecision.candidate_id || c.id === newDecision.candidateId) {
          const updatedStatus =
            newDecision.decision_status === 'reject' || newDecision.decision === 'reject'
              ? 'layout_noise'
              : 'confirmed';
          const updatedProposed = newDecision.modified_text || c.proposed_text || c.proposedText;
          return {
            ...c,
            status: updatedStatus,
            proposed_text: updatedProposed,
            decisions: [newDecision, ...(c.decisions || [])],
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

  // Selected candidate index for prev/next buttons
  const currentIndex = selectedCandidate
    ? filteredCandidates.findIndex((c) => c.id === selectedCandidate.id)
    : -1;

  // Metrics computation helpers
  const totalCount = metrics?.total_candidates ?? metrics?.totalCandidates ?? candidates.length;
  const pendingCount =
    metrics?.pending_candidates ??
    metrics?.pendingCandidates ??
    candidates.filter((c) => c.status === 'pending_review' || c.status === 'unresolved').length;
  const acceptedCount =
    metrics?.accepted_candidates ??
    metrics?.acceptedCandidates ??
    candidates.filter((c) => c.status === 'confirmed' || c.status === 'accepted').length;
  const rejectedCount =
    metrics?.rejected_candidates ??
    metrics?.rejectedCandidates ??
    candidates.filter((c) => c.status === 'layout_noise' || c.status === 'rejected').length;
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

      {errorCode && <p className="error-code">{errorCode}</p>}

      {/* Analysis Runs & Proofreading Trigger Panel */}
      <section className="panel proofreading-panel" aria-labelledby="proofread-panel-title">
        <div className="panel-header-row">
          <div>
            <p className="section-label">AI & GRAPH PROOFREADING</p>
            <h2 id="proofread-panel-title">보고서 교정 분석 실행 및 현황</h2>
          </div>
          <div className="proofread-controls">
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
            <select
              className="stage-select"
              value={versionStage}
              onChange={(e) => setVersionStage(e.target.value)}
              aria-label="버전 단계"
            >
              <option value="1차">1차 교정본</option>
              <option value="2차">2차 교정본</option>
              <option value="최종">최종 감수본</option>
            </select>
            <button
              type="button"
              className="btn-trigger-run"
              onClick={handleTriggerProofread}
              disabled={runningProofread}
            >
              {runningProofread ? '교정 분석 실행 중...' : '▶ 교정 분석 시작'}
            </button>
          </div>
        </div>

        {runResult && (
          <div className="run-result-banner">
            <strong>✓ 교정 분석 완료 (Run ID: {runResult.run_id || runResult.runId})</strong>
            <div className="run-stats-pills">
              <span>파싱 페이지: {runResult.pages_parsed ?? runResult.pagesParsed ?? 0}</span>
              <span>도판 객체 연계: {runResult.objects_resolved ?? runResult.objectsResolved ?? 0}</span>
              <span>참조 해결: {runResult.references_resolved ?? runResult.referencesResolved ?? 0}</span>
              <span>생성된 교정 후보: {runResult.candidates_count ?? runResult.candidatesCount ?? 0}건</span>
            </div>
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
              return (
                <article className="run-card" key={version.id}>
                  <div>
                    <strong>{version.originalName}</strong>
                    <span>{Math.max(1, Math.ceil(version.sizeBytes / 1024))} KB</span>
                  </div>
                  <div className="status-column">
                    <span className={`status status-${run?.status ?? 'unknown'}`}>
                      {run?.status ?? 'unknown'}
                    </span>
                    {run?.errorCode && <code>{run.errorCode}</code>}
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
              <option value="confirmed">승인 완료</option>
              <option value="layout_noise">반려 (노이즈)</option>
            </select>
          </div>

          <div className="filter-group">
            <label htmlFor="filter-severity">중요도:</label>
            <select
              id="filter-severity"
              value={filterSeverity}
              onChange={(e) => setFilterSeverity(e.target.value)}
            >
              <option value="all">전체 중요도</option>
              <option value="high">높음 (High)</option>
              <option value="medium">보통 (Medium)</option>
              <option value="low">낮음 (Low)</option>
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
                상단의 <strong>[교정 분석 시작]</strong> 버튼을 눌러 PDF 원본을 분석하세요.
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
                  onDecisionSubmitted={handleDecisionSubmitted}
                />
              )}

              {selectedCandidate && activeTab === 'graph' && (
                <EvidenceGraphExplorer
                  candidate={selectedCandidate}
                  traceability={selectedTraceability}
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
