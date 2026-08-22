import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Project, ProjectDetail, ReviewRound } from '../api';
import { ProjectDetailPage } from './ProjectDetailPage';

const apiMocks = vi.hoisted(() => ({
  getProject: vi.fn(),
  uploadDocument: vi.fn(),
  fetchCandidates: vi.fn(),
  fetchReviewRounds: vi.fn(),
  approveReviewRound: vi.fn(),
  retryAnalysisRun: vi.fn(),
}));

const graphMocks = vi.hoisted(() => ({
  createGraphFirstReviewRound: vi.fn(),
  triggerGraphFirstRun: vi.fn(),
}));

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return { ...actual, ...apiMocks };
});

vi.mock('../graphFirstReviewApi', () => graphMocks);

vi.mock('../components/ReferenceCorpusPanel', () => ({
  ReferenceCorpusPanel: ({ onReadyCorpusChange }: { onReadyCorpusChange?: (corpus: unknown) => void }) => (
    <button
      type="button"
      onClick={() => onReadyCorpusChange?.({
        id: 'corpus-1', projectId: 'proj_1', revision: 1, status: 'ready',
      })}
    >
      기준자료 READY 선택
    </button>
  ),
}));

const project: Project = { id: 'proj_1', name: '산노리', internalCode: null };

function makeDetail(overrides: Partial<ProjectDetail> = {}): ProjectDetail {
  return {
    ...project,
    documents: [
      { id: 'doc_body', projectId: 'proj_1', kind: 'report_body', title: '본문' },
    ],
    documentVersions: [
      {
        id: 'body_v1', documentId: 'doc_body', originalName: '본문.pdf', mimeType: 'application/pdf',
        sizeBytes: 2048, stage: 'source', kind: 'report_body',
      },
    ],
    analysisRuns: [],
    ...overrides,
  };
}

function graphRound(id = 'round_1', sequence = 1): ReviewRound {
  return {
    id,
    projectId: 'proj_1',
    sequence,
    status: 'reviewing',
    bodyVersionId: 'body_v1',
    referenceCorpusId: 'corpus-1',
  } as ReviewRound;
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.getProject.mockResolvedValue(makeDetail());
  apiMocks.fetchReviewRounds.mockResolvedValue([]);
  apiMocks.fetchCandidates.mockResolvedValue({ total: 0, candidates: [] });
});

describe('ProjectDetailPage graph-first inputs', () => {
  it('keeps ordinary upload for body only and never offers plate/drawing version selectors', async () => {
    render(<ProjectDetailPage project={project} />);

    const kind = await screen.findByLabelText('문서 종류');
    expect(within(kind).getByRole('option', { name: '본문' })).toBeInTheDocument();
    expect(within(kind).queryByRole('option', { name: '도판 / 사진' })).not.toBeInTheDocument();
    expect(within(kind).queryByRole('option', { name: '도면' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('도판 버전')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('도면 버전')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('이전 라운드 도판 / 사진 재사용')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('이전 라운드 도면 재사용')).not.toBeInTheDocument();
  });

  it('creates a new round from body plus the selected READY ReferenceCorpus only', async () => {
    const user = userEvent.setup();
    graphMocks.createGraphFirstReviewRound.mockResolvedValue({ ...graphRound(), status: 'draft' });
    render(<ProjectDetailPage project={project} />);

    await user.click(await screen.findByRole('button', { name: '기준자료 READY 선택' }));
    await user.click(screen.getByRole('button', { name: '+ 새 검수 라운드 생성' }));
    expect(screen.getByLabelText('본문 문서')).toHaveValue('body_v1');
    expect(screen.getByLabelText('READY 기준자료')).toHaveValue('Reference Corpus V1 (corpus-1)');
    await user.click(screen.getByRole('button', { name: '검수 라운드 생성' }));

    await waitFor(() => {
      expect(graphMocks.createGraphFirstReviewRound).toHaveBeenCalledWith('proj_1', {
        bodyVersionId: 'body_v1',
        referenceCorpusId: 'corpus-1',
        notes: null,
      });
    });
  });

  it('runs graph review with AI and VLM unchecked by default', async () => {
    const user = userEvent.setup();
    apiMocks.fetchReviewRounds.mockResolvedValue([graphRound()]);
    graphMocks.triggerGraphFirstRun.mockResolvedValue({ status: 'queued', run_id: 'run-1' });
    render(<ProjectDetailPage project={project} />);

    expect(await screen.findByLabelText('AI 문맥 심화 검토 (선택)')).not.toBeChecked();
    expect(screen.getByLabelText('VLM 시각 심화 검토 (선택)')).not.toBeChecked();
    expect(screen.getByText('Graph review는 항상 실행됩니다.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '▶ 선택 라운드 검수 실행' }));

    await waitFor(() => {
      expect(graphMocks.triggerGraphFirstRun).toHaveBeenCalledWith('proj_1', {
        reviewRoundId: 'round_1',
        enableAiReview: false,
        enableVlm: false,
      });
    });
  });

  it('shows historical legacy visual IDs read-only instead of making them inputs', async () => {
    apiMocks.fetchReviewRounds.mockResolvedValue([
      {
        ...graphRound(),
        plateVersionId: 'plate-old',
        drawingVersionId: 'drawing-old',
      },
    ]);
    render(<ProjectDetailPage project={project} />);

    expect(await screen.findByLabelText('legacy visual inputs')).toHaveTextContent('plate=plate-old');
    expect(screen.getByLabelText('legacy visual inputs')).toHaveTextContent('drawing=drawing-old');
    expect(screen.queryByRole('combobox', { name: /도판/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: /도면/ })).not.toBeInTheDocument();
  });
});

describe('ProjectDetailPage graph finding provenance', () => {
  it('labels deterministic graph findings and semantic escalations explicitly', async () => {
    apiMocks.fetchCandidates.mockResolvedValue({
      total: 2,
      candidates: [
        {
          id: 'cand-graph', status: 'pending_review', ruleCategory: 'figure_plate_table_photo_ref',
          originalText: '본문', proposedText: '(도판 45)',
          evidence: { id: 'ev1', method: 'graph_rule_engine', value: { requiresAi: false } },
        },
        {
          id: 'cand-semantic', status: 'pending_review', ruleCategory: 'direction_period_term',
          originalText: '북쪽 방향', proposedText: null,
          evidence: { id: 'ev2', method: 'graph_rule_engine', value: { requiresAi: true } },
        },
      ],
    });
    render(<ProjectDetailPage project={project} />);

    expect(await screen.findByText('Graph confirmed')).toBeInTheDocument();
    expect(screen.getByText('Human confirmation required')).toBeInTheDocument();
  });
});

describe('ProjectDetailPage operations', () => {
  it('uploads selected files as report_body without a human revision stage', async () => {
    const user = userEvent.setup();
    apiMocks.uploadDocument.mockResolvedValue({ documentVersionId: 'body_v2', analysisRunId: 'ingest_1' });
    render(<ProjectDetailPage project={project} />);

    await user.upload(
      screen.getByLabelText('원본 파일'),
      new File(['pdf'], '본문-수정.pdf', { type: 'application/pdf' }),
    );
    await waitFor(() => {
      expect(apiMocks.uploadDocument).toHaveBeenCalledWith('proj_1', expect.any(File), 'report_body');
    });
  });

  it('keeps retry and round approval available', async () => {
    const user = userEvent.setup();
    apiMocks.fetchReviewRounds.mockResolvedValue([graphRound()]);
    apiMocks.getProject.mockResolvedValue(makeDetail({
      analysisRuns: [{
        id: 'run_fail', status: 'failed', step: 'analysis', documentVersionId: 'body_v1',
        errorCode: 'analysis_error', retryable: true,
      }],
    }));
    apiMocks.retryAnalysisRun.mockResolvedValue({ analysisRunId: 'run_fail', status: 'queued' });
    apiMocks.approveReviewRound.mockResolvedValue({ ...graphRound(), status: 'approved' });
    render(<ProjectDetailPage project={project} />);

    await user.click(await screen.findByRole('button', { name: '재시도' }));
    await waitFor(() => expect(apiMocks.retryAnalysisRun).toHaveBeenCalledWith('proj_1', 'run_fail'));
    await user.click(screen.getByRole('button', { name: '✓ 검수 라운드 승인' }));
    await waitFor(() => expect(apiMocks.approveReviewRound).toHaveBeenCalledWith('proj_1', 'round_1'));
  });
});
