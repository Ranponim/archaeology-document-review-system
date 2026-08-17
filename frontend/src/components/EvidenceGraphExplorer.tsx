import { useState } from 'react';
import {
  type ArchaeologyObject,
  type CandidateVisualBundle,
  type CorrectionCandidate,
  type Evidence,
  type ReviewDecision,
  type TraceabilityResponse,
} from '../api';

type Props = {
  candidate: CorrectionCandidate;
  traceability?: TraceabilityResponse | null;
  visualBundle?: CandidateVisualBundle | null;
  loading?: boolean;
};

/**
 * Graph node model. Every node is derived from a field that the backend
 * traceability / visual-bundle payload actually returns — never synthesized.
 */
export type GraphNodeKind =
  | 'candidate'
  | 'arch_obj'
  | 'evidence'
  | 'page'
  | 'doc_ver'
  | 'decision'
  | 'canonical_asset';

export type GraphNode = {
  id: string;
  kind: GraphNodeKind;
  typeTag: string;
  title: string;
  subtitle?: string;
  statusPill?: string;
  /** Property rows shown in the detail inspector. */
  properties: Array<{ key: string; value: string }>;
  /** Property chips rendered directly on the node card (e.g. bbox, source_sha256). */
  chips?: Array<{ key: string; value: string }>;
};

export type GraphEdge = {
  from: string;
  to: string;
  label: string;
};

export type GraphModel = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

function fmt(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) {
    return `[${value.map((v) => (typeof v === 'number' ? v.toFixed(3) : String(v))).join(', ')}]`;
  }
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function prop(key: string, value: unknown): { key: string; value: string } | null {
  if (value === null || value === undefined || value === '') return null;
  return { key, value: fmt(value) };
}

function compact(
  rows: Array<{ key: string; value: string } | null>,
): Array<{ key: string; value: string }> {
  return rows.filter((r): r is { key: string; value: string } => r !== null);
}

/**
 * Build the node/edge model strictly from the API-returned traceability payload.
 *
 * Real relationships (from backend `get_candidate_traceability`):
 *   (candidate)-[:ABOUT]->(archaeology_object)
 *   (candidate)-[:SUPPORTED_BY]->(evidence)
 *   (evidence)-[:EXTRACTED_FROM]->(page)
 *   (evidence)-[:FROM_VERSION]->(document_version)
 *   (candidate)-[:HAS_DECISION]->(review_decision)
 *
 * No edge is drawn unless the corresponding node is present in the payload.
 * bbox / source_sha256 are node properties and render as chips, never as edges.
 */
export function buildGraphModel(
  candidate: CorrectionCandidate,
  traceability?: TraceabilityResponse | null,
  visualBundle?: CandidateVisualBundle | null,
): GraphModel {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];

  const candProps = traceability?.candidate ?? null;
  const candId = candProps?.id ?? candidate.id;
  const candNode: GraphNode = {
    id: candId,
    kind: 'candidate',
    typeTag: 'CorrectionCandidate',
    title: `후보: ${candId.slice(0, 14)}`,
    subtitle: candProps?.rule_category ?? candidate.rule_category ?? candidate.category ?? '검수',
    statusPill: candProps?.status ?? candidate.status,
    properties: compact([
      prop('id', candId),
      prop(
        'rule_category',
        candProps?.rule_category ?? candidate.rule_category ?? candidate.category,
      ),
      prop('status', candProps?.status ?? candidate.status),
      prop(
        'original_text',
        candProps?.original_text ?? candidate.original_text ?? candidate.originalText,
      ),
      prop(
        'proposed_text',
        candProps?.proposed_text ?? candidate.proposed_text ?? candidate.proposedText,
      ),
      prop('confidence', candProps?.confidence ?? candidate.confidence),
    ]),
  };
  nodes.push(candNode);

  // (candidate)-[:ABOUT]->(archaeology_object) — only when the object is returned.
  const archObj: ArchaeologyObject | null =
    traceability?.archaeology_object ?? traceability?.archaeologyObject ?? null;
  if (archObj && archObj.id) {
    const objNode: GraphNode = {
      id: archObj.id,
      kind: 'arch_obj',
      typeTag: 'ArchaeologyObject',
      title: archObj.id.slice(0, 14),
      subtitle: archObj.canonical_name ?? archObj.title ?? '도판/도면 객체',
      properties: compact([
        prop('id', archObj.id),
        prop('canonical_name', archObj.canonical_name),
        prop('title', archObj.title),
        prop('object_type', archObj.object_type ?? archObj.objectType),
        prop('site', archObj.site),
        prop('period', archObj.period),
      ]),
    };
    nodes.push(objNode);
    edges.push({ from: candId, to: archObj.id, label: 'ABOUT' });
  }

  // Canonical identity path (review §11): the visual-bundle `canonical` asset is
  // the DEPICTS visual asset the backend resolved for this candidate
  // ((cand)-[:ABOUT]->(obj)<-[:DEPICTS]-(asset)). Only rendered when the backend
  // returns it — never invented (anti-pattern #7/#10).
  const canonical = visualBundle?.canonical ?? null;
  if (canonical && canonical.imageUrl && archObj && archObj.id) {
    const assetTypeTag: Record<string, string> = {
      page: 'Page',
      plate: 'Plate',
      plate_panel: 'PlatePanel',
      drawing: 'Drawing',
      drawing_region: 'DrawingRegion',
    };
    const canonicalNode: GraphNode = {
      id: canonical.regionId ?? canonical.imageUrl,
      kind: 'canonical_asset',
      typeTag: assetTypeTag[canonical.assetType] ?? 'CanonicalAsset',
      title: canonical.printedIdentifier ?? canonical.regionId ?? '표준 자산',
      subtitle: canonical.caption ?? canonical.assetType,
      properties: compact([
        prop('assetType', canonical.assetType),
        prop('regionId', canonical.regionId),
        prop('printedIdentifier', canonical.printedIdentifier),
        prop('sourceSha256', canonical.sourceSha256),
        prop('physicalPage', canonical.physicalPage),
        prop('caption', canonical.caption),
      ]),
      chips: compact([prop('bbox', canonical.bbox)]),
    };
    nodes.push(canonicalNode);
    edges.push({ from: canonicalNode.id, to: archObj.id, label: 'DEPICTS' });
  }

  // (candidate)-[:SUPPORTED_BY]->(evidence) -> EXTRACTED_FROM / FROM_VERSION.
  const evidences: Evidence[] = Array.isArray(traceability?.evidence)
    ? traceability.evidence
    : traceability?.evidence
      ? [traceability.evidence]
      : [];
  evidences.forEach((ev, idx) => {
    const evId = ev.id ?? `evidence_${idx}`;
    const evNode: GraphNode = {
      id: evId,
      kind: 'evidence',
      typeTag: 'Evidence',
      title: evId.slice(0, 14),
      subtitle: `방법: ${ev.method ?? 'rule'}`,
      properties: compact([
        prop('id', evId),
        prop('kind', ev.kind),
        prop('value', ev.value),
        prop('confidence', ev.confidence),
        prop('method', ev.method),
        prop('rationale', ev.rationale),
      ]),
      chips: compact([
        prop('bbox', ev.bbox),
        prop('source_sha256', ev.source_sha256 ?? ev.sourceSha256),
      ]),
    };
    nodes.push(evNode);
    edges.push({ from: candId, to: evId, label: 'SUPPORTED_BY' });

    // (evidence)-[:EXTRACTED_FROM]->(page) — only when the page is returned.
    const page = ev.page;
    if (page && page.id) {
      const pageId = page.id;
      const pageNode: GraphNode = {
        id: pageId,
        kind: 'page',
        typeTag: 'Page',
        title: pageId.slice(0, 14),
        subtitle: `물리 ${page.physical_page ?? '?'}쪽 (인쇄 ${page.printed_page ?? '?'}쪽)`,
        properties: compact([
          prop('id', pageId),
          prop('physical_page', page.physical_page),
          prop('printed_page', page.printed_page),
          prop('header', page.header),
        ]),
      };
      nodes.push(pageNode);
      edges.push({ from: evId, to: pageId, label: 'EXTRACTED_FROM' });
    }

    // (evidence)-[:FROM_VERSION]->(document_version) — only when returned.
    const docVer = ev.document_version;
    if (docVer && docVer.id) {
      const dvId = docVer.id;
      const dvNode: GraphNode = {
        id: dvId,
        kind: 'doc_ver',
        typeTag: 'DocumentVersion',
        title: dvId.slice(0, 14),
        subtitle: `단계: ${docVer.stage ?? 'source'}`,
        properties: compact([
          prop('id', dvId),
          prop('stage', docVer.stage),
          prop('sha256', docVer.sha256),
        ]),
      };
      nodes.push(dvNode);
      edges.push({ from: evId, to: dvId, label: 'FROM_VERSION' });
    }
  });

  // (candidate)-[:HAS_DECISION]->(review_decision) — only when decisions exist.
  const decisions: ReviewDecision[] = [
    ...(candidate.decisions ?? []),
    ...(traceability?.decisions ?? []),
  ].filter((dec, idx, arr) => dec && arr.findIndex((item) => item?.id === dec.id) === idx);
  decisions.forEach((dec) => {
    const decId = dec.id;
    const decNode: GraphNode = {
      id: decId,
      kind: 'decision',
      typeTag: 'ReviewDecision',
      title: decId.slice(0, 14),
      subtitle: dec.reviewer ?? '검수관',
      statusPill: dec.decision_status ?? dec.decision ?? undefined,
      properties: compact([
        prop('id', decId),
        prop('decision_status', dec.decision_status ?? dec.decision),
        prop('reviewer', dec.reviewer),
        prop('note', dec.note ?? dec.rationale),
        prop('created_at', dec.created_at ?? dec.createdAt),
        prop('previous_decision_id', dec.previous_decision_id),
      ]),
    };
    nodes.push(decNode);
    edges.push({ from: candId, to: decId, label: 'HAS_DECISION' });
  });

  return { nodes, edges };
}

const NODE_KIND_LABEL: Record<GraphNodeKind, string> = {
  candidate: 'CorrectionCandidate (교정 후보)',
  arch_obj: 'ArchaeologyObject (표준 고고학 유물/도판 객체)',
  evidence: 'Evidence (검수 근거 데이터)',
  page: 'Page (보고서 페이지 노드)',
  doc_ver: 'DocumentVersion (문서 버전 정보)',
  decision: 'ReviewDecision (검수 판정 이력)',
  canonical_asset: 'CanonicalAsset (표준 도판/도면/패널 자산)',
};

export function EvidenceGraphExplorer({
  candidate,
  traceability,
  visualBundle,
  loading = false,
}: Props) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [activeEvidenceIndex, setActiveEvidenceIndex] = useState(0);

  if (loading) {
    return (
      <div className="graph-loading-state">
        <div className="spinner" />
        <p>지식 그래프 출처(Provenance) 및 근거 경로를 불러오는 중...</p>
      </div>
    );
  }

  const allEvidences: Evidence[] = [
    ...(candidate.evidences ?? []),
    ...(Array.isArray(traceability?.evidence) ? traceability.evidence : []),
    ...(candidate.evidence ? [candidate.evidence] : []),
  ].filter((ev, idx, arr) => ev && arr.findIndex((item) => item?.id === ev.id) === idx);

  const model = buildGraphModel(candidate, traceability, visualBundle);
  const nodeById = new Map(model.nodes.map((n) => [n.id, n]));

  const selectedNode =
    (selectedNodeId ? nodeById.get(selectedNodeId) : undefined) ??
    model.nodes.find((n) => n.kind === 'candidate') ??
    model.nodes[0];

  const activeEvidence: Evidence | undefined =
    allEvidences[activeEvidenceIndex] ?? allEvidences[0] ?? candidate.evidence;
  const activeEvidenceNode = activeEvidence
    ? nodeById.get(activeEvidence.id ?? '')
    : undefined;
  const activePageNode = activeEvidence?.page?.id
    ? nodeById.get(activeEvidence.page.id)
    : undefined;
  const activeDocVerNode = activeEvidence?.document_version?.id
    ? nodeById.get(activeEvidence.document_version.id)
    : undefined;

  const chain: Array<{ node: GraphNode; edgeToNext?: string }> = [];
  const candNode = model.nodes.find((n) => n.kind === 'candidate');
  if (candNode) {
    chain.push({ node: candNode });
    if (activeEvidenceNode) {
      chain[chain.length - 1].edgeToNext = 'SUPPORTED_BY';
      chain.push({ node: activeEvidenceNode });
      if (activePageNode) {
        chain[chain.length - 1].edgeToNext = 'EXTRACTED_FROM';
        chain.push({ node: activePageNode });
      }
      if (activeDocVerNode) {
        chain[chain.length - 1].edgeToNext = 'FROM_VERSION';
        chain.push({ node: activeDocVerNode });
      }
    }
  }

  const branchEdges = model.edges.filter(
    (e) => e.from === candNode?.id && e.label !== 'SUPPORTED_BY',
  );

  const canonicalNode = model.nodes.find((n) => n.kind === 'canonical_asset');
  const archObjNode = model.nodes.find((n) => n.kind === 'arch_obj');

  function renderNode(node: GraphNode) {
    const isActive = selectedNode?.id === node.id;
    return (
      <div
        className={`graph-node node-${node.kind} ${isActive ? 'active' : ''}`}
        onClick={() => setSelectedNodeId(node.id)}
        role="button"
        tabIndex={0}
        data-testid={`graph-node-${node.kind}`}
      >
        <div className="node-type-tag">{node.typeTag}</div>
        <div className="node-title">{node.title}</div>
        {node.subtitle && <div className="node-sub">{node.subtitle}</div>}
        {node.statusPill && <div className="node-status-pill">{node.statusPill}</div>}
        {node.chips && node.chips.length > 0 && (
          <div className="node-chip-row">
            {node.chips.map((chip) => (
              <span className="property-chip" key={chip.key} title={`${chip.key}: ${chip.value}`}>
                <span className="chip-key">{chip.key}</span>
                <span className="chip-value">{chip.value}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }

  function renderEdge(label: string) {
    return (
      <div className="path-edge" data-testid={`graph-edge-${label}`}>
        <span className="edge-label">[:{label}]</span>
        <div className="edge-line" />
      </div>
    );
  }

  return (
    <div className="evidence-graph-explorer" data-testid="evidence-graph-explorer">
      <div className="graph-header">
        <div>
          <span className="section-label">NEO4J KNOWLEDGE GRAPH PROVENANCE</span>
          <h3 className="graph-title">교정 후보 및 근거 출처 경로</h3>
          <p className="graph-desc">
            본 교정 후보가 실제 Neo4j에서 조회된 경로를 그대로 시각화합니다. 후보는
            [:ABOUT]으로 표준 고고학 객체와, [:SUPPORTED_BY]로 근거(Evidence)와 연결되고,
            근거는 [:EXTRACTED_FROM]으로 페이지, [:FROM_VERSION]으로 문서 버전과 연결됩니다.
            바운딩 박스와 원본 SHA-256 해시는 근거 노드의 속성으로 표시됩니다.
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

      <div className="graph-pathway-container">
        <div className="pathway-track">
          {chain.map((item, idx) => (
            <div className="pathway-segment" key={item.node.id}>
              {renderNode(item.node)}
              {item.edgeToNext && renderEdge(item.edgeToNext)}
            </div>
          ))}
        </div>

        {branchEdges.length > 0 && (
          <div className="graph-branches">
            {branchEdges.map((edge) => {
              const target = nodeById.get(edge.to);
              if (!target) return null;
              return (
                <div className="branch-row" key={`${edge.from}-${edge.label}-${edge.to}`}>
                  {renderEdge(edge.label)}
                  {renderNode(target)}
                </div>
              );
            })}
          </div>
        )}

        {canonicalNode && archObjNode && (
          <div className="canonical-identity-section">
            <span className="section-label">CANONICAL IDENTITY PATH</span>
            <p className="canonical-identity-desc">
              이 후보가 대조하는 표준 도판/도면 자산이 왜 선택되었는지 보여줍니다. 표준 자산은
              [:DEPICTS]로 표준 고고학 객체와 연결됩니다 (backend visual-bundle에서 반환된 관계만
              표시).
            </p>
            <div className="canonical-identity-row">
              {renderNode(canonicalNode)}
              {renderEdge('DEPICTS')}
              {renderNode(archObjNode)}
            </div>
          </div>
        )}
      </div>

      <div className="node-detail-panel">
        <div className="detail-header">
          <h4>
            노드 상세 속성 (Node Properties):{' '}
            <span className="selected-node-name">
              {NODE_KIND_LABEL[selectedNode.kind]}
            </span>
          </h4>
        </div>

        <div className="detail-body">
          {selectedNode.properties.length === 0 ? (
            <p className="muted">이 노드에 반환된 속성이 없습니다.</p>
          ) : (
            <div className="property-grid">
              {selectedNode.properties.map((row) => (
                <div className="prop-row" key={row.key}>
                  <span className="prop-key">{row.key}</span>
                  <span className="prop-val mono">{row.value}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {model.nodes.some((n) => n.kind === 'decision') && (
        <div className="decision-graph-section">
          <span className="section-label">AUDIT DECISION CHAIN</span>
          <h4>연결된 감사 결정 노드 (Chained Decisions)</h4>
          <div className="decision-node-chain">
            {model.nodes
              .filter((n) => n.kind === 'decision')
              .map((node) => (
                <div key={node.id} className="dec-node-card">
                  <div className="dec-node-header">
                    <span className="dec-node-id mono">{node.id}</span>
                    {node.statusPill && (
                      <span className={`dec-node-status status-${node.statusPill}`}>
                        {node.statusPill}
                      </span>
                    )}
                  </div>
                  <div className="dec-node-reviewer">검수자: {node.subtitle}</div>
                  {node.properties.find((p) => p.key === 'created_at') && (
                    <div className="dec-node-time">
                      {node.properties.find((p) => p.key === 'created_at')?.value}
                    </div>
                  )}
                  {node.properties.find((p) => p.key === 'previous_decision_id') && (
                    <div className="dec-node-supersedes">
                      ➔ [:SUPERSEDES] ➔{' '}
                      {node.properties.find((p) => p.key === 'previous_decision_id')?.value}
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