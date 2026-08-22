import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useState } from 'react';

import {
  type CorrectionCandidate,
  type DocumentVersion,
  type Project,
  type ProjectDetail,
  type ReviewRound,
  approveReviewRound,
  fetchCandidates,
  fetchReviewRounds,
  getProject,
  retryAnalysisRun,
  uploadDocument,
} from '../api';
import { ReferenceCorpusPanel } from '../components/ReferenceCorpusPanel';
import type { ReferenceCorpus } from '../referenceCorpusApi';
import {
  createGraphFirstReviewRound,
  triggerGraphFirstRun,
} from '../graphFirstReviewApi';

type Props = {
  project: Project;
  onBack?: () => void;
};

type ExtendedRound = ReviewRound & {
  referenceCorpusId?: string | null;
  reference_corpus_id?: string | null;
};

function bodyId(round: ReviewRound | null): string | null {
  return round?.bodyVersionId ?? round?.body_version_id ?? null;
}

function corpusId(round: ReviewRound | null): string | null {
  const item = round as ExtendedRound | null;
  return item?.referenceCorpusId ?? item?.reference_corpus_id ?? null;
}

function plateId(round: ReviewRound | null): string | null {
  return round?.plateVersionId ?? round?.plate_version_id ?? null;
}

function drawingId(round: ReviewRound | null): string | null {
  return round?.drawingVersionId ?? round?.drawing_version_id ?? null;
}

function versionKind(version: DocumentVersion, detail: ProjectDetail): string {
  if (version.kind) return version.kind;
  return detail.documents.find((doc) => doc.id === version.documentId)?.kind ?? 'report_body';
}

function provenanceLabel(candidate: CorrectionCandidate): string {
  const evidence = candidate.evidence;
  const value = evidence?.value;
  if (evidence?.method === 'graph_rule_engine') {
    if (value && typeof value === 'object' && 'requiresAi' in value && Boolean((value as { requiresAi?: boolean }).requiresAi)) {
      return 'Human confirmation required';
    }
    return 'Graph confirmed';
  }
  if (evidence?.method?.toLowerCase().includes('ai') || evidence?.method?.toLowerCase().includes('vlm')) {
    return 'AI reviewed';
  }
  return 'Human confirmation required';
}

export function GraphFirstProjectDetailPage({ project, onBack }: Props) {
  const [detail, setDetail] = useState<ProjectDetail>({
    ...project,
    documents: [],
    documentVersions: [],
    analysisRuns: [],
  });
  const [rounds, setRounds] = useState<ReviewRound[]>([]);
  const [selectedRoundId, setSelectedRoundId] = useState<string | null>(null);
  const [readyCorpus, setReadyCorpus] = useState<ReferenceCorpus | null>(null);
  const [isCreateRoundOpen, setIsCreateRoundOpen] = useState(false);
  const [newRoundBodyVersionId, setNewRoundBodyVersionId] = useState('');
  const [roundNotes, setRoundNotes] = useState('');
  const [enableAiReview, setEnableAiReview] = useState(false);
  const [enableVlm, setEnableVlm] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [creatingRound, setCreatingRound] = useState(false);
  const [running, setRunning] = useState(false);
  const [approving, setApproving] = useState(false);
  const [retryingRunId, setRetryingRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<CorrectionCandidate[]>([]);

  const loadProject = useCallback(async () => {
    const next = await getProject(project.id);
    setDetail(next);
    return next;
  }, [project.id]);

  const loadRounds = useCallback(async () => {
    const items = await fetchReviewRounds(project.id);
    setRounds(items);
    setSelectedRoundId((current) => {
      if (current && items.some((item) => item.id === current)) return current;
      return items.length ? items[items.length - 1].id : null;
    });
  }, [project.id]);

  const loadCandidates = useCallback(async () => {
    const response = await fetchCandidates(project.id).catch(() => ({ total: 0, candidates: [] }));
    setCandidates(response.candidates ?? []);
  }, [project.id]);

  useEffect(() => {
    void loadProject().catch(() => setError('server_error'));
    void loadRounds().catch(() => setError('server_error'));
    void loadCandidates();
  }, [loadCandidates, loadProject, loadRounds]);

  const bodyVersions = useMemo(
    () => detail.documentVersions.filter((version) => versionKind(version, detail) === 'report_body'),
    [detail],
  );

  const selectedRound =
    rounds.find((item) => item.id === selectedRoundId) ?? (rounds.length ? rounds[rounds.length - 1] : null);
  const selectedBodyId = bodyId(selectedRound);
  const selectedCorpusId = corpusId(selectedRound);
  const selectedLegacyPlateId = plateId(selectedRound);
  const selectedLegacyDrawingId = drawingId(selectedRound);
  const selectedRoundReady = Boolean(selectedBodyId && selectedCorpusId);

  function openCreateRound() {
    const latestBody = bodyVersions[bodyVersions.length - 1];
    setNewRoundBodyVersionId(latestBody?.id ?? '');
    setRoundNotes('');
    setError(null);
    setIsCreateRoundOpen(true);
  }

  async function handleCreateRound(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newRoundBodyVersionId || !readyCorpus) {
      setError('body_and_ready_reference_corpus_required');
      return;
    }
    setCreatingRound(true);
    setError(null);
    try {
      const created = await createGraphFirstReviewRound(project.id, {
        bodyVersionId: newRoundBodyVersionId,
        referenceCorpusId: readyCorpus.id,
        notes: roundNotes || null,
      });
      setRounds((items) => [...items, created]);
      setSelectedRoundId(created.id);
      setIsCreateRoundOpen(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'server_error');
    } finally {
      setCreatingRound(false);
    }
  }

  async function chooseBodyFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (!files.length || uploading) return;
    setUploading(true);
    setError(null);
    try {
      for (const file of files) {
        await uploadDocument(project.id, file, 'report_body');
      }
      await loadProject();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'server_error');
    } finally {
      setUploading(false);
      event.target.value = '';
    }
  }

  async function handleRun() {
    if (!selectedRound || !selectedRoundReady) {
      setError('review_round_body_and_reference_corpus_required');
      return;
    }
    setRunning(true);
    setError(null);
    setRunStatus('queued');
    try {
      const result = await triggerGraphFirstRun(project.id, {
        reviewRoundId: selectedRound.id,
        enableAiReview,
        enableVlm,
      });
      setRunStatus(result.status);
      await loadProject();
      await loadCandidates();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'server_error');
      setRunStatus('failed');
    } finally {
      setRunning(false);
    }
  }

  async function handleApprove() {
    if (!selectedRound) return;
    setApproving(true);
    setError(null);
    try {
      const updated = await approveReviewRound(project.id, selectedRound.id);
      setRounds((items) => items.map((item) => (item.id === updated.id ? { ...item, ...updated } : item)));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'server_error');
    } finally {
      setApproving(false);
    }
  }

  async function handleRetry(runId: string) {
    if (retryingRunId) return;
    setRetryingRunId(runId);
    setError(null);
    try {
      await retryAnalysisRun(project.id, runId);
      await loadProject();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'server_error');
    } finally {
      setRetryingRunId(null);
    }
  }

  return (
    <main className="project-detail-page graph-first-project-detail">
      <header className="project-detail-header">
        <div>
          <p className="section-label">GRAPH-FIRST REVIEW</p>
          <h2>{project.name}</h2>
          <p>본문 + READY ReferenceCorpus가 검수 라운드의 유일한 신규 입력입니다.</p>
        </div>
        {onBack && <button type="button" onClick={onBack}>← 프로젝트 목록</button>}
      </header>

      {error && <p role="alert">{error}</p>}

      <section aria-labelledby="body-upload-title">
        <h3 id="body-upload-title">본문 원본</h3>
        <label>
          문서 종류
          <select aria-label="문서 종류" value="report_body" disabled>
            <option value="report_body">본문</option>
          </select>
        </label>
        <span aria-label="회차 관리 안내">회차는 검수 라운드에서 자동 관리됩니다.</span>
        <label>
          원본 파일
          <input
            aria-label="원본 파일"
            type="file"
            accept="application/pdf,.pdf"
            multiple
            disabled={uploading}
            onChange={(event) => void chooseBodyFiles(event)}
          />
        </label>
        <ul>
          {bodyVersions.map((version) => <li key={version.id}>{version.originalName}</li>)}
        </ul>
      </section>

      <ReferenceCorpusPanel projectId={project.id} onReadyCorpusChange={setReadyCorpus} />

      <section aria-labelledby="round-title">
        <div>
          <h3 id="round-title">검수 라운드</h3>
          <button type="button" onClick={openCreateRound}>+ 새 검수 라운드 생성</button>
        </div>

        <div role="tablist" aria-label="실행 대상 검수 라운드">
          {rounds.map((round) => (
            <button
              key={round.id}
              type="button"
              role="tab"
              aria-selected={round.id === selectedRound?.id}
              onClick={() => setSelectedRoundId(round.id)}
            >
              검수 #{round.sequence} · {round.status}
            </button>
          ))}
        </div>

        {isCreateRoundOpen && (
          <form onSubmit={(event) => void handleCreateRound(event)}>
            <label>
              본문 문서
              <select
                aria-label="본문 문서"
                value={newRoundBodyVersionId}
                onChange={(event) => setNewRoundBodyVersionId(event.target.value)}
              >
                <option value="">본문 선택</option>
                {bodyVersions.map((version) => (
                  <option key={version.id} value={version.id}>{version.originalName}</option>
                ))}
              </select>
            </label>
            <label>
              READY 기준자료
              <input
                aria-label="READY 기준자료"
                readOnly
                value={readyCorpus ? `Reference Corpus V${readyCorpus.revision} (${readyCorpus.id})` : ''}
                placeholder="위에서 기준 그래프를 READY로 만드세요"
              />
            </label>
            <label>
              라운드 메모
              <input value={roundNotes} onChange={(event) => setRoundNotes(event.target.value)} />
            </label>
            <button type="submit" disabled={creatingRound || !newRoundBodyVersionId || !readyCorpus}>
              검수 라운드 생성
            </button>
          </form>
        )}

        {selectedRound && (
          <div aria-label="선택 라운드 입력">
            <p>본문: {selectedBodyId ?? '없음'}</p>
            <p>ReferenceCorpus: {selectedCorpusId ?? '없음'}</p>
            {(selectedLegacyPlateId || selectedLegacyDrawingId) && (
              <p aria-label="legacy visual inputs">
                Legacy visual IDs (읽기 전용): plate={selectedLegacyPlateId ?? '-'}, drawing={selectedLegacyDrawingId ?? '-'}
              </p>
            )}
          </div>
        )}

        <fieldset>
          <legend>검수 실행</legend>
          <p>Graph review는 항상 실행됩니다.</p>
          <label>
            <input
              type="checkbox"
              checked={enableAiReview}
              onChange={(event) => setEnableAiReview(event.target.checked)}
            />
            AI 문맥 심화 검토 (선택)
          </label>
          <label>
            <input
              type="checkbox"
              checked={enableVlm}
              onChange={(event) => setEnableVlm(event.target.checked)}
            />
            VLM 시각 심화 검토 (선택)
          </label>
          <button type="button" disabled={running || !selectedRoundReady} onClick={() => void handleRun()}>
            ▶ 선택 라운드 검수 실행
          </button>
          {runStatus && <span>실행 상태: {runStatus}</span>}
        </fieldset>

        {selectedRound && (
          <button type="button" disabled={approving} onClick={() => void handleApprove()}>
            {selectedRound.status === 'approved' ? '✓ 승인 완료 (Approved)' : '✓ 검수 라운드 승인'}
          </button>
        )}
      </section>

      <section aria-labelledby="run-history-title">
        <h3 id="run-history-title">실행 이력</h3>
        {detail.analysisRuns.map((run) => (
          <div key={run.id}>
            <span>{run.id} · {run.status} · {run.step}</span>
            {run.status === 'failed' && run.retryable && (
              <button type="button" disabled={retryingRunId === run.id} onClick={() => void handleRetry(run.id)}>
                재시도
              </button>
            )}
          </div>
        ))}
      </section>

      <section aria-labelledby="candidate-title">
        <h3 id="candidate-title">검수 후보</h3>
        <ul>
          {candidates.map((candidate) => (
            <li key={candidate.id}>
              <strong>{candidate.ruleCategory ?? candidate.rule_category ?? candidate.category ?? 'finding'}</strong>
              {' · '}
              <span>{provenanceLabel(candidate)}</span>
              <div>{candidate.originalText ?? candidate.original_text ?? ''}</div>
              <div>{candidate.proposedText ?? candidate.proposed_text ?? ''}</div>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
