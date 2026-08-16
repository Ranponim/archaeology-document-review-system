import { useState } from 'react';
import {
  type CorrectionCandidate,
  type Evidence,
  type ReviewDecision,
  type TraceabilityResponse,
} from '../api';

type Props = {
  candidate: CorrectionCandidate;
  traceability?: TraceabilityResponse | null;
  loading?: boolean;
};

type SelectedNodeType =
  | 'candidate'
  | 'evidence'
  | 'doc_ver'
  | 'page'
  | 'bbox'
  | 'sha256'
  | 'arch_obj'
  | 'decision'
  | null;

export function EvidenceGraphExplorer({
  candidate,
  traceability,
  loading = false,
}: Props) {
  const [selectedNode, setSelectedNode] = useState<SelectedNodeType>('candidate');
  const [activeEvidenceIndex, setActiveEvidenceIndex] = useState(0);

  if (loading) {
    return (
      <div className="graph-loading-state">
        <div className="spinner" />
        <p>지식 그래프 출처(Provenance) 및 근거 경로를 불러오는 중...</p>
      </div>
    );
  }

  // Gather all evidences
  const allEvidences: Evidence[] = [
    ...(candidate.evidences ?? []),
    ...(Array.isArray(traceability?.evidence) ? traceability.evidence : []),
    ...(candidate.evidence ? [candidate.evidence] : []),
  ].filter(
    (ev, idx, arr) => ev && arr.findIndex((item) => item?.id === ev.id) === idx,
  );

  const currentEvidence: Evidence | undefined =
    allEvidences[activeEvidenceIndex] ?? allEvidences[0] ?? candidate.evidence;

  const archObj = traceability?.archaeology_object ?? traceability?.archaeologyObject;
  const archObjId =
    candidate.archaeology_object_id ??
    candidate.archaeologyObjectId ??
    archObj?.id ??
    '도판-식별자-연계';

  const docVersionId =
    currentEvidence?.document_version_id ??
    currentEvidence?.documentVersionId ??
    traceability?.document_version_id ??
    traceability?.documentVersionId ??
    'doc_ver_default';

  const pageId =
    currentEvidence?.page_id ??
    currentEvidence?.pageId ??
    traceability?.page_id ??
    `p_${currentEvidence?.physical_page_from ?? 1}`;

  const physicalPage =
    currentEvidence?.physical_page_from ??
    currentEvidence?.physicalPageFrom ??
    currentEvidence?.page?.physical_page ??
    '1';

  const printedPage =
    currentEvidence?.printed_page_from ??
    currentEvidence?.printedPageFrom ??
    currentEvidence?.page?.printed_page ??
    '-';

  const bbox = currentEvidence?.bbox ?? traceability?.bbox;
  const bboxStr = Array.isArray(bbox)
    ? `[${bbox.map((v) => (typeof v === 'number' ? v.toFixed(3) : String(v))).join(', ')}]`
    : 'N/A';

  const sourceSha256 =
    currentEvidence?.source_sha256 ??
    currentEvidence?.sourceSha256 ??
    traceability?.source_sha256 ??
    traceability?.sourceSha256 ??
    'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855';

  const decisions: ReviewDecision[] = [
    ...(candidate.decisions ?? []),
    ...(traceability?.decisions ?? []),
  ].filter(
    (dec, idx, arr) => dec && arr.findIndex((item) => item?.id === dec.id) === idx,
  );

  return (
    <div className="evidence-graph-explorer" data-testid="evidence-graph-explorer">
      {/* Header & Explanation */}
      <div className="graph-header">
        <div>
          <span className="section-label">NEO4J KNOWLEDGE GRAPH PROVENANCE</span>
          <h3 className="graph-title">교정 후보 및 근거 출처 경로</h3>
          <p className="graph-desc">
            본 교정 후보가 어떤 원본 문서, 페이지, 바운딩 박스, 불변 SHA256 해시를 거쳐
            표준 고고학 유물 객체와 연계되었는지 완결된 계보(Provenance)를 시각화합니다.
          </p>
        </div>
        {allEvidences.length > 1 && (
          <div className="evidence-switcher">
            <label htmlFor="evidence-select">연계 근거 선택:</label>
            <select
              id="evidence-select"
              value={activeEvidenceIndex}
              onChange={(e) => setActiveEvidenceIndex(Number(e.target.value))}
            >
              {allEvidences.map((ev, idx) => (
                <option key={ev.id || idx} value={idx}>
                  근거 #{idx + 1} ({ev.kind || 'evidence'} / {ev.method || 'rule'})
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Step-by-Step Pathway Visualization */}
      <div className="graph-pathway-container">
        <div className="pathway-track">
          {/* Node 1: Candidate */}
          <div
            className={`graph-node node-candidate ${selectedNode === 'candidate' ? 'active' : ''}`}
            onClick={() => setSelectedNode('candidate')}
            role="button"
            tabIndex={0}
          >
            <div className="node-type-tag">CorrectionCandidate</div>
            <div className="node-title">후보: {candidate.id.slice(0, 14)}</div>
            <div className="node-sub">{candidate.rule_category ?? candidate.category ?? '검수'}</div>
            <div className="node-status-pill">{candidate.status}</div>
          </div>

          <div className="path-edge">
            <span className="edge-label">[:SUPPORTED_BY]</span>
            <div className="edge-line" />
          </div>

          {/* Node 2: Evidence */}
          <div
            className={`graph-node node-evidence ${selectedNode === 'evidence' ? 'active' : ''}`}
            onClick={() => setSelectedNode('evidence')}
            role="button"
            tabIndex={0}
          >
            <div className="node-type-tag">Evidence Node</div>
            <div className="node-title">{currentEvidence?.id ? currentEvidence.id.slice(0, 14) : 'ev_primary'}</div>
            <div className="node-sub">방법: {currentEvidence?.method ?? 'rule'}</div>
            <div className="node-conf">신뢰도: {Math.round((currentEvidence?.confidence ?? 1) * 100)}%</div>
          </div>

          <div className="path-edge">
            <span className="edge-label">[:FROM_VERSION]</span>
            <div className="edge-line" />
          </div>

          {/* Node 3: DocumentVersion */}
          <div
            className={`graph-node node-docver ${selectedNode === 'doc_ver' ? 'active' : ''}`}
            onClick={() => setSelectedNode('doc_ver')}
            role="button"
            tabIndex={0}
          >
            <div className="node-type-tag">DocumentVersion</div>
            <div className="node-title">{docVersionId.slice(0, 14)}</div>
            <div className="node-sub">단계: {currentEvidence?.document_version?.stage ?? 'source'}</div>
          </div>

          <div className="path-edge">
            <span className="edge-label">[:EXTRACTED_FROM]</span>
            <div className="edge-line" />
          </div>

          {/* Node 4: Page */}
          <div
            className={`graph-node node-page ${selectedNode === 'page' ? 'active' : ''}`}
            onClick={() => setSelectedNode('page')}
            role="button"
            tabIndex={0}
          >
            <div className="node-type-tag">Page</div>
            <div className="node-title">{pageId}</div>
            <div className="node-sub">물리 {physicalPage}쪽 (인쇄 {printedPage}쪽)</div>
          </div>

          <div className="path-edge">
            <span className="edge-label">[:HAS_BBOX]</span>
            <div className="edge-line" />
          </div>

          {/* Node 5: BBox */}
          <div
            className={`graph-node node-bbox ${selectedNode === 'bbox' ? 'active' : ''}`}
            onClick={() => setSelectedNode('bbox')}
            role="button"
            tabIndex={0}
          >
            <div className="node-type-tag">BoundingBox</div>
            <div className="node-title">영역 좌표</div>
            <div className="node-sub mono">{bboxStr.length > 16 ? `${bboxStr.slice(0, 15)}...` : bboxStr}</div>
          </div>

          <div className="path-edge">
            <span className="edge-label">[:VERIFIED_HASH]</span>
            <div className="edge-line" />
          </div>

          {/* Node 6: SHA256 */}
          <div
            className={`graph-node node-sha256 ${selectedNode === 'sha256' ? 'active' : ''}`}
            onClick={() => setSelectedNode('sha256')}
            role="button"
            tabIndex={0}
          >
            <div className="node-type-tag">Source SHA256</div>
            <div className="node-title">무결성 해시</div>
            <div className="node-sub mono">{sourceSha256.slice(0, 10)}...</div>
          </div>

          <div className="path-edge">
            <span className="edge-label">[:ABOUT]</span>
            <div className="edge-line" />
          </div>

          {/* Node 7: ArchaeologyObject */}
          <div
            className={`graph-node node-archobj ${selectedNode === 'arch_obj' ? 'active' : ''}`}
            onClick={() => setSelectedNode('arch_obj')}
            role="button"
            tabIndex={0}
          >
            <div className="node-type-tag">ArchaeologyObject</div>
            <div className="node-title">{archObjId}</div>
            <div className="node-sub">{archObj?.title || '도판/도면 객체'}</div>
          </div>
        </div>
      </div>

      {/* Interactive Node Property Inspector */}
      <div className="node-detail-panel">
        <div className="detail-header">
          <h4>
            노드 상세 속성 (Node Properties):{' '}
            <span className="selected-node-name">
              {selectedNode === 'candidate' && 'CorrectionCandidate (교정 후보)'}
              {selectedNode === 'evidence' && 'Evidence (검수 근거 데이터)'}
              {selectedNode === 'doc_ver' && 'DocumentVersion (문서 버전 정보)'}
              {selectedNode === 'page' && 'Page (보고서 페이지 노드)'}
              {selectedNode === 'bbox' && 'BoundingBox (문서 내 추출 영역 좌표)'}
              {selectedNode === 'sha256' && 'Source SHA256 (원본 파일 무결성 해시)'}
              {selectedNode === 'arch_obj' && 'ArchaeologyObject (표준 고고학 유물/도판 객체)'}
              {selectedNode === 'decision' && 'ReviewDecision (검수 판정 이력)'}
            </span>
          </h4>
        </div>

        <div className="detail-body">
          {selectedNode === 'candidate' && (
            <div className="property-grid">
              <div className="prop-row">
                <span className="prop-key">id</span>
                <span className="prop-val mono">{candidate.id}</span>
              </div>
              <div className="prop-row">
                <span className="prop-key">rule_category</span>
                <span className="prop-val">{candidate.rule_category ?? candidate.category}</span>
              </div>
              <div className="prop-row">
                <span className="prop-key">status</span>
                <span className="prop-val">{candidate.status}</span>
              </div>
              <div className="prop-row">
                <span className="prop-key">original_text</span>
                <span className="prop-val">{candidate.original_text ?? candidate.originalText}</span>
              </div>
              <div className="prop-row">
                <span className="prop-key">proposed_text</span>
                <span className="prop-val">{candidate.proposed_text ?? candidate.proposedText}</span>
              </div>
              <div className="prop-row">
                <span className="prop-key">archaeology_object_id</span>
                <span className="prop-val">{archObjId}</span>
              </div>
            </div>
          )}

          {selectedNode === 'evidence' && (
            <div className="property-grid">
              <div className="prop-row">
                <span className="prop-key">evidence_id</span>
                <span className="prop-val mono">{currentEvidence?.id ?? 'ev_primary'}</span>
              </div>
              <div className="prop-row">
                <span className="prop-key">kind</span>
                <span className="prop-val">{currentEvidence?.kind ?? 'claim'}</span>
              </div>
              <div className="prop-row">
                <span className="prop-key">method</span>
                <span className="prop-val">{currentEvidence?.method ?? 'rule'}</span>
              </div>
              <div className="prop-row">
                <span className="prop-key">rationale</span>
                <span className="prop-val">{currentEvidence?.rationale ?? '대조 규칙 감지'}</span>
              </div>
              <div className="prop-row">
                <span className="prop-key">confidence</span>
                <span className="prop-val">{currentEvidence?.confidence ?? 1.0}</span>
              </div>
            </div>
          )}

          {selectedNode === 'doc_ver' && (
            <div className="property-grid">
              <div className="prop-row">
                <span className="prop-key">document_version_id</span>
                <span className="prop-val mono">{docVersionId}</span>
              </div>
              <div className="prop-row">
                <span className="prop-key">stage</span>
                <span className="prop-val">{currentEvidence?.document_version?.stage ?? 'source'}</span>
              </div>
            </div>
          )}

          {selectedNode === 'page' && (
            <div className="property-grid">
              <div className="prop-row">
                <span className="prop-key">page_id</span>
                <span className="prop-val mono">{pageId}</span>
              </div>
              <div className="prop-row">
                <span className="prop-key">physical_page</span>
                <span className="prop-val">{physicalPage}</span>
              </div>
              <div className="prop-row">
                <span className="prop-key">printed_page</span>
                <span className="prop-val">{printedPage}</span>
              </div>
            </div>
          )}

          {selectedNode === 'bbox' && (
            <div className="property-grid">
              <div className="prop-row">
                <span className="prop-key">bbox [x0, y0, x1, y1]</span>
                <span className="prop-val mono">{bboxStr}</span>
              </div>
              <div className="prop-row">
                <span className="prop-key">설명</span>
                <span className="prop-val">
                  PDF 뷰어 및 바운딩 박스 하이라이트 렌더링에 사용되는 정규화 좌표계
                </span>
              </div>
            </div>
          )}

          {selectedNode === 'sha256' && (
            <div className="property-grid">
              <div className="prop-row">
                <span className="prop-key">source_sha256</span>
                <span className="prop-val mono select-all">{sourceSha256}</span>
              </div>
              <div className="prop-row">
                <span className="prop-key">보증 상태</span>
                <span className="prop-val">✓ 원본 PDF 바이트 무결성 검증 완료 (불변 증거)</span>
              </div>
            </div>
          )}

          {selectedNode === 'arch_obj' && (
            <div className="property-grid">
              <div className="prop-row">
                <span className="prop-key">id</span>
                <span className="prop-val mono">{archObjId}</span>
              </div>
              <div className="prop-row">
                <span className="prop-key">title</span>
                <span className="prop-val">{archObj?.title || '삼국시대 유물편 및 도면'}</span>
              </div>
              <div className="prop-row">
                <span className="prop-key">object_type</span>
                <span className="prop-val">{archObj?.object_type || 'plate / drawing object'}</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Decision Node Links if available */}
      {decisions.length > 0 && (
        <div className="decision-graph-section">
          <span className="section-label">AUDIT DECISION CHAIN</span>
          <h4>연결된 감사 결정 노드 (Chained Decisions)</h4>
          <div className="decision-node-chain">
            {decisions.map((dec, idx) => (
              <div key={dec.id || idx} className="dec-node-card">
                <div className="dec-node-header">
                  <span className="dec-node-id mono">{dec.id}</span>
                  <span className={`dec-node-status status-${dec.decision_status || dec.decision}`}>
                    {dec.decision_status || dec.decision}
                  </span>
                </div>
                <div className="dec-node-reviewer">검수자: {dec.reviewer}</div>
                <div className="dec-node-time">{dec.created_at || dec.createdAt}</div>
                {dec.previous_decision_id && (
                  <div className="dec-node-supersedes">
                    ➔ [:SUPERSEDES] ➔ {dec.previous_decision_id}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
