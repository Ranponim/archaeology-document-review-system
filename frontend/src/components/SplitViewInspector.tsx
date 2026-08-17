import { useEffect, useState } from 'react';
import {
  type CandidateVisualBundle,
  type CorrectionCandidate,
  type Evidence,
  type ReviewDecision,
  type ReviewDecisionPayload,
  type TraceabilityResponse,
  fetchVisualBundle,
  submitReviewDecision,
} from '../api';
import { VisualAssetPane } from './VisualAssetPane';

type Props = {
  projectId: string;
  candidate: CorrectionCandidate;
  traceability?: TraceabilityResponse | null;
  visualBundle?: CandidateVisualBundle | null;
  onDecisionSubmitted?: (decision: ReviewDecision) => void;
};

function isDrawingType(assetType: string | undefined): boolean {
  return assetType === 'drawing' || assetType === 'drawing_region';
}

export function SplitViewInspector({
  projectId,
  candidate,
  traceability,
  visualBundle: visualBundleProp,
  onDecisionSubmitted,
}: Props) {
  const [reviewer, setReviewer] = useState('고고학 전문 검수관');
  const [decisionType, setDecisionType] = useState<
    'accepted' | 'rejected' | 'modified' | 'deferred'
  >('accepted');
  const [rationale, setRationale] = useState('');
  const [modifiedText, setModifiedText] = useState(
    candidate.proposed_text ?? candidate.proposedText ?? '',
  );
  const [isPending, setIsPending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [copiedHash, setCopiedHash] = useState(false);

  const [visualBundle, setVisualBundle] = useState<CandidateVisualBundle | null>(null);
  const [loadingVisual, setLoadingVisual] = useState(false);
  const [visualError, setVisualError] = useState<string | null>(null);

  useEffect(() => {
    if (visualBundleProp) {
      setVisualBundle(visualBundleProp);
      setLoadingVisual(false);
      setVisualError(null);
      return;
    }
    let isMounted = true;
    setLoadingVisual(true);
    setVisualError(null);
    setVisualBundle(null);
    fetchVisualBundle(projectId, candidate.id)
      .then((bundle) => {
        if (isMounted) setVisualBundle(bundle);
      })
      .catch(() => {
        if (isMounted) setVisualError('시각 자산(본문 페이지/도판/도면)을 불러오지 못했습니다.');
      })
      .finally(() => {
        if (isMounted) setLoadingVisual(false);
      });
    return () => {
      isMounted = false;
    };
  }, [projectId, candidate.id, visualBundleProp]);

  const sourceAsset = visualBundle?.source ?? null;
  const canonicalAsset = visualBundle?.canonical ?? null;
  const canonicalIsDrawing = canonicalAsset ? isDrawingType(canonicalAsset.assetType) : false;

  const originalText = candidate.original_text ?? candidate.originalText ?? '';
  const proposedText = candidate.proposed_text ?? candidate.proposedText ?? '';
  const category = candidate.rule_category ?? candidate.category ?? '일반 검수';
  const severity = candidate.severity ?? 'medium';
  const status = candidate.status ?? 'pending_review';
  const latestDecision: ReviewDecision | null =
    candidate.latest_decision ?? candidate.latestDecision ?? null;
  const latestOutcome = latestDecision?.decision_status ?? latestDecision?.decision ?? null;

  // Primary and secondary evidence resolution
  const primaryEvidence: Evidence | undefined =
    candidate.evidence ??
    (Array.isArray(traceability?.evidence)
      ? traceability?.evidence[0]
      : (traceability?.evidence as Evidence | undefined)) ??
    candidate.evidences?.[0];

  const allEvidences: Evidence[] = [
    ...(candidate.evidences ?? []),
    ...(Array.isArray(traceability?.evidence) ? traceability.evidence : []),
  ].filter(
    (ev, idx, arr) => ev && arr.findIndex((item) => item?.id === ev.id) === idx,
  );

  const sourceSha256 =
    primaryEvidence?.source_sha256 ??
    primaryEvidence?.sourceSha256 ??
    traceability?.source_sha256 ??
    traceability?.sourceSha256 ??
    '해시 정보 없음';

  const docVersionId =
    primaryEvidence?.document_version_id ??
    primaryEvidence?.documentVersionId ??
    traceability?.document_version_id ??
    traceability?.documentVersionId ??
    'doc_ver_unknown';

  const pageNum =
    primaryEvidence?.physical_page_from ??
    primaryEvidence?.physicalPageFrom ??
    primaryEvidence?.page?.physical_page ??
    primaryEvidence?.page_id ??
    traceability?.page_id ??
    '미상';

  const printedPageNum =
    primaryEvidence?.printed_page_from ??
    primaryEvidence?.printedPageFrom ??
    primaryEvidence?.page?.printed_page ??
    '';

  const bbox = primaryEvidence?.bbox ?? traceability?.bbox;
  const bboxText = Array.isArray(bbox)
    ? `[${bbox.map((v) => (typeof v === 'number' ? v.toFixed(2) : String(v))).join(', ')}]`
    : '전체 영역';

  const archObj = traceability?.archaeology_object ?? traceability?.archaeologyObject;
  const archObjId =
    candidate.archaeology_object_id ??
    candidate.archaeologyObjectId ??
    archObj?.id ??
    '【도판 식별자 미지정】';

  // Decisions list
  const decisions: ReviewDecision[] = [
    ...(candidate.decisions ?? []),
    ...(traceability?.decisions ?? []),
  ].filter(
    (dec, idx, arr) => dec && arr.findIndex((item) => item?.id === dec.id) === idx,
  );

  async function handleActionSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!reviewer.trim()) {
      setActionError('검수자 이름을 입력해주세요.');
      return;
    }

    setActionError(null);
    setActionSuccess(null);
    setIsPending(true);

    const payload: ReviewDecisionPayload = {
      decision: decisionType,
      reviewer: reviewer.trim(),
      rationale: rationale.trim(),
      note: rationale.trim(),
      modified_text: decisionType === 'modified' ? modifiedText.trim() : null,
    };

    const decisionLabel: Record<string, string> = {
      accepted: '승인',
      rejected: '반려',
      modified: '수정',
      deferred: '보류',
    };

    try {
      const result = await submitReviewDecision(projectId, candidate.id, payload);
      setActionSuccess(
        `검수 판정 [${decisionLabel[decisionType] ?? decisionType}]이 성공적으로 기록되었습니다.`,
      );
      if (onDecisionSubmitted) {
        onDecisionSubmitted(result);
      }
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '판정 기록 중 오류가 발생했습니다.');
    } finally {
      setIsPending(false);
    }
  }

  function handleCopyHash() {
    if (sourceSha256 && sourceSha256 !== '해시 정보 없음') {
      void navigator.clipboard.writeText(sourceSha256);
      setCopiedHash(true);
      setTimeout(() => setCopiedHash(false), 2000);
    }
  }

  return (
    <div className="split-view-inspector" data-testid="split-view-inspector">
      {/* Top Meta Bar */}
      <header className="inspector-header">
        <div className="inspector-title-group">
          <div className="badge-row">
            <span className={`status-badge status-${latestOutcome ?? status}`}>
              {latestOutcome === 'accepted'
                ? '✓ 승인 완료'
                : latestOutcome === 'rejected'
                  ? '✕ 반려'
                  : latestOutcome === 'modified'
                    ? '✎ 수정 승인'
                    : latestOutcome === 'deferred'
                      ? '⏸ 보류'
                      : '⏳ 검수 대기'}
            </span>
            <span className={`severity-tag severity-${severity}`}>
              중요도: {severity.toUpperCase()}
            </span>
            <span className="category-tag">{category}</span>
          </div>
          <h3 className="candidate-heading">
            교정 후보 ID: <code>{candidate.id}</code>
          </h3>
        </div>
        <div className="inspector-algo-meta">
          <span className="confidence-label">
            알고리즘 신뢰도: {Math.round((candidate.confidence ?? 1.0) * 100)}%
          </span>
          <span className="confidence-sub">
            (주의: VLM/규칙 엔진의 확률적 수치이며 최종 고고학 판정이 아닙니다)
          </span>
        </div>
      </header>

      {/* Side-by-Side Comparison Container */}
      <div className="split-panes-grid">
        {/* LEFT PANE: Source Document Claim */}
        <section className="pane-card source-pane" aria-labelledby="source-pane-heading">
          <div className="pane-header">
            <span className="pane-tag">SOURCE CLAIM (본문 원본)</span>
            <h4 id="source-pane-heading">원본 추출 문맥 및 주장</h4>
          </div>

          {loadingVisual && (
            <div className="visual-loading" role="status">
              <div className="spinner" />
              <p>본문 페이지 렌더를 불러오는 중...</p>
            </div>
          )}
          {visualError && <p className="visual-error">{visualError}</p>}
          {!loadingVisual && sourceAsset && (
            <VisualAssetPane
              asset={sourceAsset}
              title="본문 PDF — 실제 렌더 페이지"
              subtitle={
                sourceAsset.physicalPage != null
                  ? `물리 ${sourceAsset.physicalPage}쪽`
                  : undefined
              }
              testIdPrefix="source"
            />
          )}

          <div className="pane-meta-grid">
            <div className="meta-item">
              <span className="meta-label">문서 버전:</span>
              <span className="meta-value"><code>{docVersionId}</code></span>
            </div>
            <div className="meta-item">
              <span className="meta-label">페이지 위치:</span>
              <span className="meta-value">
                물리 {pageNum}쪽 {printedPageNum ? `(본문 인쇄 ${printedPageNum}쪽)` : ''}
              </span>
            </div>
            <div className="meta-item">
              <span className="meta-label">BBOX 좌표:</span>
              <span className="meta-value bbox-code"><code>{bboxText}</code></span>
            </div>
            <div className="meta-item hash-item">
              <span className="meta-label">원본 무결성 해시:</span>
              <div className="hash-wrap">
                <code className="sha-code" title={sourceSha256}>
                  {sourceSha256.length > 20
                    ? `${sourceSha256.slice(0, 10)}...${sourceSha256.slice(-8)}`
                    : sourceSha256}
                </code>
                <button
                  type="button"
                  className="btn-tiny"
                  onClick={handleCopyHash}
                  title="SHA-256 전체 복사"
                >
                  {copiedHash ? '복사됨!' : '복사'}
                </button>
              </div>
            </div>
          </div>

          <div className="claim-box">
            <p className="box-sublabel">보고서 본문 추출 문장</p>
            <blockquote className="claim-text">
              {originalText || '(추출된 원본 텍스트 없음)'}
            </blockquote>
          </div>

          {primaryEvidence && (
            <div className="evidence-summary-box">
              <span className="box-sublabel">추출 근거 (Evidence Detail)</span>
              <p className="evidence-rationale">
                <strong>[방식: {primaryEvidence.method ?? 'rule'}]</strong>{' '}
                {primaryEvidence.rationale || '규칙 기반 대조 패턴 감지'}
              </p>
              {allEvidences.length > 1 && (
                <p className="more-evidence-count">
                  + 추가 근거 {allEvidences.length - 1}건 연결됨
                </p>
              )}
            </div>
          )}
        </section>

        {/* RIGHT PANE: Canonical Target & VLM Observation */}
        <section className="pane-card canonical-pane" aria-labelledby="canonical-pane-heading">
          <div className="pane-header">
            <span className="pane-tag">CANONICAL TARGET (표준 대조군)</span>
            <h4 id="canonical-pane-heading">도면·도판 대조 표준 및 제안</h4>
          </div>

          {!loadingVisual && canonicalAsset && !canonicalIsDrawing && (
            <VisualAssetPane
              asset={canonicalAsset}
              title="표준 도판 / 사진 — 실제 패널 이미지"
              subtitle={canonicalAsset.printedIdentifier ?? undefined}
              testIdPrefix="canonical"
            />
          )}
          {!loadingVisual && canonicalIsDrawing && (
            <p className="visual-note">
              이 후보의 표준 대조 자산은 도면입니다. 아래 [표준 도면] 영역에서 실제 도면 렌더와
              영역 하이라이트를 확인하세요.
            </p>
          )}

          <div className="pane-meta-grid">
            <div className="meta-item">
              <span className="meta-label">대상 유물/도판:</span>
              <span className="meta-value canonical-id-highlight">
                <strong>{archObjId}</strong>
              </span>
            </div>
            <div className="meta-item">
              <span className="meta-label">도판/도면 명칭:</span>
              <span className="meta-value">
                {archObj?.title || '도판/도면 명칭 연계됨'}
              </span>
            </div>
            {archObj?.object_type && (
              <div className="meta-item">
                <span className="meta-label">유물 분류:</span>
                <span className="meta-value">{archObj.object_type}</span>
              </div>
            )}
          </div>

          {/* Diff Box */}
          <div className="proposed-box">
            <p className="box-sublabel">제안된 교정 내용 (Proposed Revision)</p>
            <div className="diff-view">
              <div className="diff-row diff-original">
                <span className="diff-label">기존 원본:</span>
                <span className="diff-content">{originalText}</span>
              </div>
              <div className="diff-row diff-proposed">
                <span className="diff-label">교정 제안:</span>
                <span className="diff-content">{proposedText || '(삭제 또는 미지정)'}</span>
              </div>
            </div>
          </div>

          {/* VLM / AI Observation Box */}
          <div className="vlm-observation-box">
            <div className="vlm-header">
              <span className="vlm-tag">VLM 비전 분석 관찰 소견</span>
              <span className="vlm-confidence">
                AI 예측도: {Math.round((primaryEvidence?.confidence ?? candidate.confidence ?? 0.9) * 100)}%
              </span>
            </div>
            <p className="vlm-verdict-text">
              {archObj?.vlm_verdict ||
                primaryEvidence?.rationale ||
                '도판 내 유물 번호와 본문 서술 간의 번호 상이점 교차 검증됨.'}
            </p>
            <div className="vlm-warning-callout" role="note">
              <strong>⚠️ AI 관찰 결과 안내:</strong> 위 VLM 및 규칙 소견은 인공지능 보조 알고리즘에
              의한 예측이며, 최종 고고학적 확정이 아닙니다. 전문 검수자의 학술적 확인이 필요합니다.
            </div>
          </div>
        </section>
      </div>

      {/* CANONICAL DRAWING SECTION (review §9) */}
      {!loadingVisual && canonicalAsset && canonicalIsDrawing && (
        <section className="pane-card drawing-pane" aria-labelledby="drawing-pane-heading">
          <div className="pane-header">
            <span className="pane-tag">CANONICAL DRAWING (표준 도면)</span>
            <h4 id="drawing-pane-heading">표준 도면 — 실제 렌더 및 영역 하이라이트</h4>
          </div>
          <VisualAssetPane
            asset={canonicalAsset}
            title="표준 도면 — 실제 렌더"
            subtitle={canonicalAsset.printedIdentifier ?? undefined}
            testIdPrefix="drawing"
          />
        </section>
      )}

      {/* EXPERT REVIEW ACTION FORM */}
      <section className="review-action-section" aria-labelledby="action-heading">
        <h4 id="action-heading" className="section-subtitle">
          전문가 검수 판정 (Audit Decision)
        </h4>

        <form onSubmit={handleActionSubmit} className="review-form">
          <div className="form-row-2col">
            <div className="form-field">
              <label htmlFor="reviewer-input">검수자 성명 / 직책</label>
              <input
                id="reviewer-input"
                type="text"
                value={reviewer}
                onChange={(e) => setReviewer(e.target.value)}
                placeholder="예: 홍길동 연구원"
                required
              />
            </div>

            <div className="form-field">
              <label>판정 구분</label>
              <div className="decision-buttons-group">
                <button
                  type="button"
                  className={`btn-decision btn-accept ${decisionType === 'accepted' ? 'active' : ''}`}
                  onClick={() => setDecisionType('accepted')}
                >
                  ✓ 승인 (Accept)
                </button>
                <button
                  type="button"
                  className={`btn-decision btn-reject ${decisionType === 'rejected' ? 'active' : ''}`}
                  onClick={() => setDecisionType('rejected')}
                >
                  ✕ 반려 (Reject)
                </button>
                <button
                  type="button"
                  className={`btn-decision btn-modify ${decisionType === 'modified' ? 'active' : ''}`}
                  onClick={() => setDecisionType('modified')}
                >
                  ✎ 수정 승인 (Modify)
                </button>
                <button
                  type="button"
                  className={`btn-decision btn-defer ${decisionType === 'deferred' ? 'active' : ''}`}
                  onClick={() => setDecisionType('deferred')}
                >
                  ⏸ 보류 (Defer)
                </button>
              </div>
            </div>
          </div>

          {decisionType === 'modified' && (
            <div className="form-field full-width">
              <label htmlFor="modified-text-input">수정할 본문 텍스트</label>
              <textarea
                id="modified-text-input"
                rows={2}
                value={modifiedText}
                onChange={(e) => setModifiedText(e.target.value)}
                placeholder="수정하여 반영할 올바른 서술 문구를 입력하세요."
                required
              />
            </div>
          )}

          <div className="form-field full-width">
            <label htmlFor="rationale-input">검수 사유 및 고고학적 근거 (Rationale)</label>
            <textarea
              id="rationale-input"
              rows={2}
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              placeholder="예: 보고서 도판 12의 3번 유물 명칭 및 번호와 대조하여 본문 오탈자 수정 승인함."
            />
          </div>

          <div className="action-footer">
            <button
              type="submit"
              className="btn-primary-action"
              disabled={isPending || !reviewer.trim()}
            >
              {isPending ? '기록 중...' : '검수 판정 저장 및 감사로그 반영'}
            </button>
          </div>

          {actionSuccess && <p className="action-success-msg">{actionSuccess}</p>}
          {actionError && <p className="action-error-msg">{actionError}</p>}
        </form>
      </section>

      {/* AUDIT DECISION HISTORY TIMELINE */}
      {decisions.length > 0 && (
        <section className="decision-history-section" aria-labelledby="history-heading">
          <h4 id="history-heading" className="section-subtitle">
            검수 이력 감사 로그 (Chained via [:SUPERSEDES])
          </h4>
          <div className="decision-timeline">
            {decisions.map((dec, index) => (
              <div className="decision-timeline-item" key={dec.id || index}>
                <div className="timeline-badge">
                  {dec.decision_status === 'accepted' || dec.decisionStatus === 'accepted' || dec.decision === 'accepted' ? (
                    <span className="badge-acc">승인</span>
                  ) : dec.decision_status === 'rejected' || dec.decisionStatus === 'rejected' || dec.decision === 'rejected' ? (
                    <span className="badge-rej">반려</span>
                  ) : dec.decision_status === 'deferred' || dec.decisionStatus === 'deferred' || dec.decision === 'deferred' ? (
                    <span className="badge-def">보류</span>
                  ) : (
                    <span className="badge-mod">수정</span>
                  )}
                </div>
                <div className="timeline-content">
                  <div className="timeline-header">
                    <strong>{dec.reviewer || '검수관'}</strong>
                    <span className="timeline-time">{dec.created_at ?? dec.createdAt ?? '방금 전'}</span>
                    {dec.previous_decision_id && (
                      <span className="supersedes-tag">
                        이전 판정({dec.previous_decision_id}) 갱신
                      </span>
                    )}
                  </div>
                  {(dec.note || dec.rationale) && (
                    <p className="timeline-note">{dec.note || dec.rationale}</p>
                  )}
                  {dec.modified_text && (
                    <div className="timeline-mod-text">
                      <span className="mod-label">수정된 텍스트:</span> {dec.modified_text}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
