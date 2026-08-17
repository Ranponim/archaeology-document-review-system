import { useEffect, useState } from 'react';
import {
  type CandidateVisualBundle,
  type CorrectionCandidate,
  type Evidence,
  type ReviewDecision,
  type ReviewDecisionPayload,
  type TraceabilityResponse,
  type VisualAssetMetadata,
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

type ComparisonType =
  | 'version_change'
  | 'plate_reference'
  | 'drawing_reference'
  | 'text_evidence';

type RenderStatus = 'ready' | 'missing_render' | 'not_applicable';

type VisualReferenceMetadata = {
  type: string;
  number: string;
  referenceId?: string | null;
  reference_id?: string | null;
  targetId?: string | null;
  target_id?: string | null;
};

type EvidenceAwareVisualBundle = CandidateVisualBundle & {
  comparisonType?: ComparisonType;
  comparison_type?: ComparisonType;
  comparison?: VisualAssetMetadata | null;
  reference?: VisualReferenceMetadata | null;
  renderStatus?: RenderStatus;
  render_status?: RenderStatus;
  unresolved_reason?: string | null;
};

function isDrawingType(assetType: string | undefined): boolean {
  return assetType === 'drawing' || assetType === 'drawing_region';
}

function inferLegacyComparisonType(
  candidate: CorrectionCandidate,
  canonicalAsset: VisualAssetMetadata | null,
  comparisonAsset: VisualAssetMetadata | null,
): ComparisonType {
  if (comparisonAsset) return 'version_change';
  if (canonicalAsset && isDrawingType(canonicalAsset.assetType)) return 'drawing_reference';
  if (canonicalAsset) return 'plate_reference';

  const category = candidate.rule_category ?? candidate.ruleCategory ?? candidate.category ?? '';
  if (category === 'figure_plate_table_photo_ref') return 'plate_reference';
  return 'text_evidence';
}

function RenderDiagnostic({
  asset,
  reference,
  unresolvedReason,
}: {
  asset: VisualAssetMetadata | null;
  reference: VisualReferenceMetadata | null;
  unresolvedReason: string | null;
}) {
  const targetId = reference?.targetId ?? reference?.target_id ?? asset?.regionId ?? null;

  return (
    <div className="visual-asset-pane fallback-pane render-diagnostic" data-testid="render-diagnostic">
      <div className="visual-asset-header">
        <span className="visual-asset-title">Graph 대상은 확인됨 — 렌더 파일 사용 불가</span>
      </div>
      <div className="visual-asset-fallback-box">
        <div className="fallback-icon">⚠️</div>
        <p className="fallback-main-msg">대조 대상의 식별자는 확정되었지만 이미지 렌더를 제공할 수 없습니다.</p>
        <p className="fallback-sub-msg">
          이 상태는 “도판/도면이 없음”이 아니라 Graph의 RESOLVES_TO 대상과 렌더 파일 사이의 문제입니다.
        </p>
      </div>
      <div className="pane-meta-grid">
        {targetId && (
          <div className="meta-item">
            <span className="meta-label">Graph target ID:</span>
            <span className="meta-value"><code>{targetId}</code></span>
          </div>
        )}
        {asset?.documentVersionId && (
          <div className="meta-item">
            <span className="meta-label">DocumentVersion:</span>
            <span className="meta-value"><code>{asset.documentVersionId}</code></span>
          </div>
        )}
        {asset?.physicalPage != null && (
          <div className="meta-item">
            <span className="meta-label">물리 페이지:</span>
            <span className="meta-value">{asset.physicalPage}</span>
          </div>
        )}
        <div className="meta-item">
          <span className="meta-label">Render status:</span>
          <span className="meta-value"><code>missing_render</code></span>
        </div>
        {unresolvedReason && (
          <div className="meta-item">
            <span className="meta-label">원인 코드:</span>
            <span className="meta-value"><code>{unresolvedReason}</code></span>
          </div>
        )}
      </div>
    </div>
  );
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

  const evidenceAwareBundle = visualBundle as EvidenceAwareVisualBundle | null;
  const sourceAsset = evidenceAwareBundle?.source ?? null;
  const comparisonAsset = evidenceAwareBundle?.comparison ?? null;
  const canonicalAsset = evidenceAwareBundle?.canonical ?? null;
  const reference = evidenceAwareBundle?.reference ?? null;
  const unresolvedReason =
    evidenceAwareBundle?.unresolvedReason ?? evidenceAwareBundle?.unresolved_reason ?? null;
  const renderStatus =
    evidenceAwareBundle?.renderStatus ?? evidenceAwareBundle?.render_status ?? 'not_applicable';
  const comparisonType =
    evidenceAwareBundle?.comparisonType ??
    evidenceAwareBundle?.comparison_type ??
    inferLegacyComparisonType(candidate, canonicalAsset, comparisonAsset);

  const originalText = candidate.original_text ?? candidate.originalText ?? '';
  const proposedText = candidate.proposed_text ?? candidate.proposedText ?? '';
  const category = candidate.rule_category ?? candidate.category ?? '일반 검수';
  const severity = candidate.severity ?? 'medium';
  const status = candidate.status ?? 'pending_review';
  const latestDecision: ReviewDecision | null =
    candidate.latest_decision ?? candidate.latestDecision ?? null;
  const latestOutcome = latestDecision?.decision_status ?? latestDecision?.decision ?? null;

  const primaryEvidence: Evidence | undefined =
    candidate.evidence ??
    (Array.isArray(traceability?.evidence)
      ? traceability?.evidence[0]
      : (traceability?.evidence as Evidence | undefined)) ??
    candidate.evidences?.[0];

  const allEvidences: Evidence[] = [
    ...(candidate.evidence ? [candidate.evidence] : []),
    ...(candidate.evidences ?? []),
    ...(Array.isArray(traceability?.evidence) ? traceability.evidence : []),
  ].filter(
    (ev, idx, arr) => ev && arr.findIndex((item) => item?.id === ev.id) === idx,
  );
  const vlmEvidence = allEvidences.find((ev) => ev.kind === 'vlm_observation');

  const sourceSha256 =
    primaryEvidence?.source_sha256 ??
    primaryEvidence?.sourceSha256 ??
    traceability?.source_sha256 ??
    traceability?.sourceSha256 ??
    sourceAsset?.sourceSha256 ??
    '해시 정보 없음';

  const docVersionId =
    primaryEvidence?.document_version_id ??
    primaryEvidence?.documentVersionId ??
    traceability?.document_version_id ??
    traceability?.documentVersionId ??
    sourceAsset?.documentVersionId ??
    'doc_ver_unknown';

  const pageNum =
    primaryEvidence?.physical_page_from ??
    primaryEvidence?.physicalPageFrom ??
    primaryEvidence?.page?.physical_page ??
    primaryEvidence?.page_id ??
    traceability?.page_id ??
    sourceAsset?.physicalPage ??
    '미상';

  const printedPageNum =
    primaryEvidence?.printed_page_from ??
    primaryEvidence?.printedPageFrom ??
    primaryEvidence?.page?.printed_page ??
    '';

  const bbox = primaryEvidence?.bbox ?? traceability?.bbox ?? sourceAsset?.bbox;
  const bboxText = Array.isArray(bbox)
    ? `[${bbox.map((v) => (typeof v === 'number' ? v.toFixed(2) : String(v))).join(', ')}]`
    : '전체 영역';

  const archObj = traceability?.archaeology_object ?? traceability?.archaeologyObject;
  const archObjId =
    candidate.archaeology_object_id ??
    candidate.archaeologyObjectId ??
    archObj?.id ??
    '객체 식별자 없음';

  const decisions: ReviewDecision[] = [
    ...(candidate.decisions ?? []),
    ...(traceability?.decisions ?? []),
  ].filter(
    (dec, idx, arr) => dec && arr.findIndex((item) => item?.id === dec.id) === idx,
  );

  const referenceNumber = reference?.number ?? canonicalAsset?.printedIdentifier ?? '';
  const referenceTargetId = reference?.targetId ?? reference?.target_id ?? canonicalAsset?.regionId ?? null;

  const comparisonHeading =
    comparisonType === 'version_change'
      ? '비교 근거: 본문 수정본 간 비교'
      : comparisonType === 'plate_reference'
        ? `비교 근거: 본문 ↔ 도판 ${referenceNumber || '식별자 미상'}`
        : comparisonType === 'drawing_reference'
          ? `비교 근거: 본문 ↔ 도면 ${referenceNumber || '식별자 미상'}`
          : '비교 근거: 규칙 기반 본문 Evidence';

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
      if (onDecisionSubmitted) onDecisionSubmitted(result);
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

      <div className="comparison-grounding-banner" role="note">
        <strong>{comparisonHeading}</strong>
        {unresolvedReason && (
          <span className="comparison-warning"> · Graph/렌더 상태: {unresolvedReason}</span>
        )}
      </div>

      <div className="split-panes-grid">
        <section className="pane-card source-pane" aria-labelledby="source-pane-heading">
          <div className="pane-header">
            <span className="pane-tag">
              {comparisonType === 'version_change'
                ? 'PREVIOUS VERSION (이전 본문)'
                : 'SOURCE CLAIM (본문 근거)'}
            </span>
            <h4 id="source-pane-heading">
              {comparisonType === 'version_change' ? '이전 본문' : '원본 추출 문맥 및 주장'}
            </h4>
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
              title={
                comparisonType === 'version_change'
                  ? '이전 본문 PDF — 실제 렌더 페이지'
                  : '본문 PDF — 실제 렌더 페이지'
              }
              subtitle={
                sourceAsset.physicalPage != null
                  ? `물리 ${sourceAsset.physicalPage}쪽`
                  : undefined
              }
              testIdPrefix="source"
            />
          )}
          {!loadingVisual && !sourceAsset && (
            <VisualAssetPane
              asset={null}
              title={
                comparisonType === 'version_change'
                  ? '이전 본문 PDF — 실제 렌더 페이지'
                  : '본문 PDF — 실제 렌더 페이지'
              }
              testIdPrefix="source"
              fallbackMessage={
                comparisonType === 'version_change'
                  ? '이전 본문 렌더 provenance 없음'
                  : '본문 시각 에셋 렌더링 준비 중'
              }
            />
          )}

          <div className="pane-meta-grid">
            <div className="meta-item">
              <span className="meta-label">문서 버전:</span>
              <span className="meta-value"><code>{sourceAsset?.documentVersionId ?? docVersionId}</code></span>
            </div>
            <div className="meta-item">
              <span className="meta-label">페이지 위치:</span>
              <span className="meta-value">
                물리 {sourceAsset?.physicalPage ?? pageNum}쪽 {printedPageNum ? `(본문 인쇄 ${printedPageNum}쪽)` : ''}
              </span>
            </div>
            <div className="meta-item">
              <span className="meta-label">BBOX 좌표:</span>
              <span className="meta-value bbox-code"><code>{bboxText}</code></span>
            </div>
            <div className="meta-item hash-item">
              <span className="meta-label">원본 무결성 해시:</span>
              <div className="hash-wrap">
                <code className="sha-code" title={sourceAsset?.sourceSha256 ?? sourceSha256}>
                  {(sourceAsset?.sourceSha256 ?? sourceSha256).length > 20
                    ? `${(sourceAsset?.sourceSha256 ?? sourceSha256).slice(0, 10)}...${(sourceAsset?.sourceSha256 ?? sourceSha256).slice(-8)}`
                    : sourceAsset?.sourceSha256 ?? sourceSha256}
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
            <p className="box-sublabel">
              {comparisonType === 'version_change' ? '이전 본문 값/문장' : '보고서 본문 추출 문장'}
            </p>
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
                <p className="more-evidence-count">+ 추가 근거 {allEvidences.length - 1}건 연결됨</p>
              )}
            </div>
          )}
        </section>

        <section className="pane-card canonical-pane" aria-labelledby="canonical-pane-heading">
          <div className="pane-header">
            <span className="pane-tag">
              {comparisonType === 'version_change'
                ? 'CURRENT VERSION (현재 본문)'
                : comparisonType === 'plate_reference'
                  ? 'RESOLVED PLATE (도판 대조)'
                  : comparisonType === 'drawing_reference'
                    ? 'RESOLVED DRAWING (도면 대조)'
                    : 'TEXT EVIDENCE (본문 규칙 근거)'}
            </span>
            <h4 id="canonical-pane-heading">
              {comparisonType === 'version_change'
                ? '현재 본문'
                : comparisonType === 'plate_reference'
                  ? '도판 대조 표준 및 제안'
                  : comparisonType === 'drawing_reference'
                    ? '도면 대조 표준 및 제안'
                    : '규칙 기반 Evidence 및 제안'}
            </h4>
          </div>

          {!loadingVisual && comparisonType === 'version_change' && comparisonAsset && (
            <VisualAssetPane
              asset={comparisonAsset}
              title="현재 본문 PDF — 실제 렌더 페이지"
              subtitle={
                comparisonAsset.physicalPage != null
                  ? `물리 ${comparisonAsset.physicalPage}쪽`
                  : undefined
              }
              testIdPrefix="comparison"
            />
          )}
          {!loadingVisual && comparisonType === 'version_change' && !comparisonAsset && (
            <VisualAssetPane
              asset={null}
              title="현재 본문 PDF — 실제 렌더 페이지"
              testIdPrefix="comparison"
              fallbackMessage="현재 본문 렌더 provenance 없음"
            />
          )}

          {!loadingVisual && comparisonType === 'plate_reference' && renderStatus === 'missing_render' && (
            <RenderDiagnostic
              asset={canonicalAsset}
              reference={reference}
              unresolvedReason={unresolvedReason}
            />
          )}
          {!loadingVisual && comparisonType === 'plate_reference' && renderStatus !== 'missing_render' && canonicalAsset && (
            <VisualAssetPane
              asset={canonicalAsset}
              title="표준 도판 / 사진 — 실제 패널 이미지"
              subtitle={canonicalAsset.printedIdentifier ?? undefined}
              testIdPrefix="canonical"
            />
          )}
          {!loadingVisual && comparisonType === 'plate_reference' && renderStatus !== 'missing_render' && !canonicalAsset && (
            <VisualAssetPane
              asset={null}
              title="표준 도판 / 사진 — 실제 패널 이미지"
              testIdPrefix="canonical"
              fallbackMessage="도판 Reference는 있으나 canonical target이 확정되지 않음"
            />
          )}

          {!loadingVisual && comparisonType === 'drawing_reference' && renderStatus === 'missing_render' && (
            <RenderDiagnostic
              asset={canonicalAsset}
              reference={reference}
              unresolvedReason={unresolvedReason}
            />
          )}
          {!loadingVisual && comparisonType === 'drawing_reference' && renderStatus !== 'missing_render' && canonicalAsset && (
            <VisualAssetPane
              asset={canonicalAsset}
              title="표준 도면 — 실제 렌더 및 영역 하이라이트"
              subtitle={canonicalAsset.printedIdentifier ?? undefined}
              testIdPrefix="drawing"
            />
          )}
          {!loadingVisual && comparisonType === 'drawing_reference' && renderStatus !== 'missing_render' && !canonicalAsset && (
            <VisualAssetPane
              asset={null}
              title="표준 도면 — 실제 렌더 및 영역 하이라이트"
              testIdPrefix="drawing"
              fallbackMessage="도면 Reference는 있으나 canonical target이 확정되지 않음"
            />
          )}

          {comparisonType === 'text_evidence' && (
            <div className="evidence-summary-box text-evidence-comparison" data-testid="text-evidence-comparison">
              <span className="box-sublabel">이 후보는 시각 자산 비교 대상이 아닙니다.</span>
              <p className="evidence-rationale">
                도판/도면을 임의로 연결하지 않고, Candidate에 연결된 규칙 및 본문 Evidence만 검수 근거로 사용합니다.
              </p>
              {allEvidences.length > 0 && (
                <ul className="evidence-list">
                  {allEvidences.map((ev) => (
                    <li key={ev.id}>
                      <strong>{ev.kind ?? ev.method ?? 'evidence'}:</strong>{' '}
                      {ev.rationale ?? '세부 근거 설명 없음'}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {comparisonType === 'version_change' && (
            <div className="pane-meta-grid">
              <div className="meta-item">
                <span className="meta-label">이전 DocumentVersion:</span>
                <span className="meta-value"><code>{sourceAsset?.documentVersionId ?? 'provenance 없음'}</code></span>
              </div>
              <div className="meta-item">
                <span className="meta-label">현재 DocumentVersion:</span>
                <span className="meta-value"><code>{comparisonAsset?.documentVersionId ?? 'provenance 없음'}</code></span>
              </div>
              <div className="meta-item">
                <span className="meta-label">Render status:</span>
                <span className="meta-value"><code>{renderStatus}</code></span>
              </div>
            </div>
          )}

          {(comparisonType === 'plate_reference' || comparisonType === 'drawing_reference') && (
            <div className="pane-meta-grid">
              <div className="meta-item">
                <span className="meta-label">Graph Reference:</span>
                <span className="meta-value">
                  {reference?.type ?? (comparisonType === 'drawing_reference' ? 'drawing' : 'plate')} {reference?.number ?? '미상'}
                </span>
              </div>
              <div className="meta-item">
                <span className="meta-label">Resolved target:</span>
                <span className="meta-value canonical-id-highlight">
                  <strong>{referenceTargetId ?? 'target 미확정'}</strong>
                </span>
              </div>
              <div className="meta-item">
                <span className="meta-label">DocumentVersion:</span>
                <span className="meta-value"><code>{canonicalAsset?.documentVersionId ?? '미상'}</code></span>
              </div>
              <div className="meta-item">
                <span className="meta-label">대상 유물/객체:</span>
                <span className="meta-value"><strong>{archObjId}</strong></span>
              </div>
              {archObj?.title && (
                <div className="meta-item">
                  <span className="meta-label">객체 명칭:</span>
                  <span className="meta-value">{archObj.title}</span>
                </div>
              )}
              <div className="meta-item">
                <span className="meta-label">Render status:</span>
                <span className="meta-value"><code>{renderStatus}</code></span>
              </div>
            </div>
          )}

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

          {vlmEvidence && (
            <div className="vlm-observation-box">
              <div className="vlm-header">
                <span className="vlm-tag">VLM 비전 분석 관찰 소견</span>
                <span className="vlm-confidence">
                  AI 예측도: {Math.round((vlmEvidence.confidence ?? candidate.confidence ?? 0) * 100)}%
                </span>
              </div>
              <p className="vlm-verdict-text">{vlmEvidence.rationale ?? 'VLM 관찰 세부 설명 없음'}</p>
              <div className="vlm-warning-callout" role="note">
                <strong>⚠️ AI 관찰 결과 안내:</strong> 위 VLM 소견은 인공지능 보조 관찰이며 최종 고고학적 확정이 아닙니다. 전문 검수자의 학술적 확인이 필요합니다.
              </div>
            </div>
          )}
        </section>
      </div>

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
                      <span className="supersedes-tag">이전 판정({dec.previous_decision_id}) 갱신</span>
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
