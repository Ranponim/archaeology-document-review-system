import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { CorrectionCandidate, TraceabilityResponse } from '../api';
import {
  EvidenceGraphExplorer,
  buildGraphModel,
} from './EvidenceGraphExplorer';

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return { ...actual };
});

const candidate: CorrectionCandidate = {
  id: 'cand_trace_1',
  rule_category: 'figure_plate_table_photo_ref',
  status: 'pending_review',
  original_text: '도면 : ',
  proposed_text: '도면 : 57',
  confidence: 0.95,
};

// Real-shaped payload mirroring backend `get_candidate_traceability`.
const traceability: TraceabilityResponse = {
  candidate: {
    id: 'cand_trace_1',
    rule_category: 'figure_plate_table_photo_ref',
    change_type: 'modified',
    status: 'pending_review',
    original_text: '도면 : ',
    proposed_text: '도면 : 57',
    confidence: 0.95,
  },
  archaeology_object: {
    id: 'obj_site1_cist_6',
    canonical_name: '1지점 청동기시대 6호 석관묘',
    site: '1지점',
    period: '청동기시대',
  },
  evidence: [
    {
      id: 'ev_trace_1',
      kind: 'reference',
      source_sha256: 'sha256_ver1_full',
      document_version_id: 'ver_1',
      page_id: 'ver_1_p105',
      bbox: [15.0, 25.0, 110.0, 35.0],
      method: 'reference_aligner',
      value: '도면 : 57',
      rationale: 'Matched drawing 57 caption on page 111',
      confidence: 0.95,
      page: {
        id: 'ver_1_p105',
        physical_page: 105,
        printed_page: 101,
        header: '백제문화유산연구원 | 101',
      },
      document_version: {
        id: 'ver_1',
        sha256: 'sha256_ver1_full',
        stage: '1차',
      },
    },
  ],
  decisions: [
    {
      id: 'dec_1',
      decision_status: 'accepted',
      note: 'Verified by researcher',
      reviewer: 'archaeologist_kim',
    },
  ],
  latest_decision: { id: 'dec_1', decision_status: 'accepted' },
};

describe('EvidenceGraphExplorer real graph rendering', () => {
  it('renders candidate, evidence, page, version and object nodes from a real payload', () => {
    render(
      <EvidenceGraphExplorer candidate={candidate} traceability={traceability} />,
    );

    expect(screen.getByTestId('graph-node-candidate')).toBeInTheDocument();
    expect(screen.getByTestId('graph-node-evidence')).toBeInTheDocument();
    expect(screen.getByTestId('graph-node-page')).toBeInTheDocument();
    expect(screen.getByTestId('graph-node-doc_ver')).toBeInTheDocument();
    expect(screen.getByTestId('graph-node-arch_obj')).toBeInTheDocument();
    expect(screen.getByTestId('graph-node-decision')).toBeInTheDocument();
  });

  it('renders exactly the real edges present in the payload', () => {
    render(
      <EvidenceGraphExplorer candidate={candidate} traceability={traceability} />,
    );

    expect(screen.getByTestId('graph-edge-ABOUT')).toBeInTheDocument();
    expect(screen.getByTestId('graph-edge-SUPPORTED_BY')).toBeInTheDocument();
    expect(screen.getByTestId('graph-edge-EXTRACTED_FROM')).toBeInTheDocument();
    expect(screen.getByTestId('graph-edge-FROM_VERSION')).toBeInTheDocument();
    expect(screen.getByTestId('graph-edge-HAS_DECISION')).toBeInTheDocument();
  });

  it('does not fabricate RESOLVES_TO / DEPICTS / REFERENCES edges', () => {
    render(
      <EvidenceGraphExplorer candidate={candidate} traceability={traceability} />,
    );

    expect(screen.queryByTestId('graph-edge-RESOLVES_TO')).toBeNull();
    expect(screen.queryByTestId('graph-edge-DEPICTS')).toBeNull();
    expect(screen.queryByTestId('graph-edge-REFERENCES')).toBeNull();
    expect(screen.queryByText(/RESOLVES_TO/)).toBeNull();
    expect(screen.queryByText(/DEPICTS/)).toBeNull();
    expect(screen.queryByText(/REFERENCES/)).toBeNull();
  });

  it('renders bbox and source_sha256 as property chips, not edges', () => {
    render(
      <EvidenceGraphExplorer candidate={candidate} traceability={traceability} />,
    );

    expect(screen.queryByTestId('graph-edge-HAS_BBOX')).toBeNull();
    expect(screen.queryByTestId('graph-edge-VERIFIED_HASH')).toBeNull();
    expect(screen.queryByText(/HAS_BBOX/)).toBeNull();
    expect(screen.queryByText(/VERIFIED_HASH/)).toBeNull();

    const chips = screen.getAllByText(/bbox|source_sha256/);
    expect(chips.length).toBeGreaterThan(0);
    expect(screen.getByText('bbox')).toBeInTheDocument();
    expect(screen.getByText('source_sha256')).toBeInTheDocument();
  });

  it('draws no EXTRACTED_FROM / FROM_VERSION / ABOUT edge when those nodes are absent', () => {
    const sparse: TraceabilityResponse = {
      candidate: { id: 'cand_sparse', status: 'pending_review' },
      evidence: [
        {
          id: 'ev_sparse',
          kind: 'text_claim',
          source_sha256: 'hash_sparse',
          method: 'rule',
          value: 'sample',
        },
      ],
    };

    render(<EvidenceGraphExplorer candidate={candidate} traceability={sparse} />);

    expect(screen.getByTestId('graph-edge-SUPPORTED_BY')).toBeInTheDocument();
    expect(screen.queryByTestId('graph-edge-ABOUT')).toBeNull();
    expect(screen.queryByTestId('graph-edge-EXTRACTED_FROM')).toBeNull();
    expect(screen.queryByTestId('graph-edge-FROM_VERSION')).toBeNull();
    expect(screen.queryByTestId('graph-node-arch_obj')).toBeNull();
    expect(screen.queryByTestId('graph-node-page')).toBeNull();
    expect(screen.queryByTestId('graph-node-doc_ver')).toBeNull();
  });
});

describe('buildGraphModel payload mapping', () => {
  it('builds edges only for relationships present in the payload', () => {
    const model = buildGraphModel(candidate, traceability);
    const labels = model.edges.map((e) => e.label).sort();
    expect(labels).toEqual(
      ['ABOUT', 'EXTRACTED_FROM', 'FROM_VERSION', 'HAS_DECISION', 'SUPPORTED_BY'].sort(),
    );
  });

  it('keeps bbox and source_sha256 as evidence chips, never edges', () => {
    const model = buildGraphModel(candidate, traceability);
    const edgeLabels = model.edges.map((e) => e.label);
    expect(edgeLabels).not.toContain('HAS_BBOX');
    expect(edgeLabels).not.toContain('VERIFIED_HASH');

    const evidenceNode = model.nodes.find((n) => n.kind === 'evidence');
    expect(evidenceNode?.chips?.map((c) => c.key)).toEqual(
      expect.arrayContaining(['bbox', 'source_sha256']),
    );
  });
});