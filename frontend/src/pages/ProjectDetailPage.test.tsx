import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Project, ProjectDetail, ReviewRound } from '../api';
import { ProjectDetailPage } from './ProjectDetailPage';

const apiMocks = vi.hoisted(() => ({
  getProject: vi.fn(),
  uploadDocument: vi.fn(),
  triggerProofreadingRun: vi.fn(),
  fetchCandidates: vi.fn(),
  fetchMetrics: vi.fn(),
  fetchTraceability: vi.fn(),
  fetchVisualBundle: vi.fn(),
  retryAnalysisRun: vi.fn(),
  fetchReviewRounds: vi.fn(),
  createReviewRound: vi.fn(),
  approveReviewRound: vi.fn(),
}));

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return { ...actual, ...apiMocks };
});

const project: Project = { id: 'proj_1', name: '산노리', internalCode: null };

function makeDetail(overrides: Partial<ProjectDetail> = {}): ProjectDetail {
  return {
    ...project,
    documents: [
      { id: 'doc_body', projectId: 'proj_1', kind: 'report_body', title: '본문' },
      { id: 'doc_plate', projectId: 'proj_1', kind: 'plate_book', title: '도판 / 사진' },
      { id: 'doc_draw', projectId: 'proj_1', kind: 'drawing_book', title: '도면' },
    ],
    documentVersions: [
      {
        id: 'body_v1', documentId: 'doc_body', originalName: '본문.pdf', mimeType: 'application/pdf',
        sizeBytes: 2048, stage: 'source', kind: 'report_body',
      },
      {
        id: 'plate_v1', documentId: 'doc_plate', originalName: '도판.pdf', mimeType: 'application/pdf',
        sizeBytes: 2048, stage: 'source', kind: 'plate_book',
      },
      {
        id: 'drawing_v1', documentId: 'doc_draw', originalName: '도면.pdf', mimeType: 'application/pdf',
        sizeBytes: 2048, stage: 'source', kind: 'drawing_book',
      },
    ],
    analysisRuns: [],
    ...overrides,
  };
}

function round(id = 'round_1', sequence = 1): ReviewRound {
  return {
    id,
    projectId: 'proj_1',
    sequence,
    status: 'reviewing',
    bodyVersionId: 'body_v1',
    plateVersionId: 'plate_v1',
    drawingVersionId: 'drawing_v1',
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.getProject.mockResolvedValue(makeDetail());
  apiMocks.fetchReviewRounds.mockResolvedValue([]);
  apiMocks.fetchCandidates.mockResolvedValue({ total: 0, candidates: [] });
  apiMocks.fetchMetrics.mockResolvedValue({});
  apiMocks.fetchTraceability.mockResolvedValue({});
  apiMocks.fetchVisualBundle.mockResolvedValue({ candidateId: 'candidate_1' });
});

describe('ProjectDetailPage ReviewRound input model', () => {
  it('asks for document kind but never asks the user to choose 1차/2차/3차/final', async () => {
    render(<ProjectDetailPage project={project} />);

    const kind = await screen.findByLabelText('문서 종류');
    expect(within(kind).getByRole('option', { name: '본문' })).toBeInTheDocument();
    expect(within(kind).getByRole('option', { name: '도판 / 사진' })).toBeInTheDocument();
    expect(within(kind).getByRole('option', { name: '도면' })).toBeInTheDocument();
    expect(screen.queryByLabelText('교정 단계')).not.toBeInTheDocument();
    expect(screen.getByLabelText('회차 관리 안내')).toHaveTextContent('검수 라운드에서 자동 관리');
  });

  it('does not expose body/plate/drawing selectors again in the run form', async () => {
    apiMocks.fetchReviewRounds.mockResolvedValue([round()]);
    render(<ProjectDetailPage project={project} />);

    expect(await screen.findByLabelText('실행 대상 검수 라운드')).toHaveTextContent('검수 #1');
    expect(screen.queryByLabelText('본문 버전')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('도판 버전')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('도면 버전')).not.toBeInTheDocument();
  });

  it('runs exactly the selected review round, not the latest round or manual version combination', async () => {
    const user = userEvent.setup();
    apiMocks.fetchReviewRounds.mockResolvedValue([round('round_1', 1), round('round_2', 2)]);
    apiMocks.triggerProofreadingRun.mockResolvedValue({
      run_id: 'run_selected', project_id: 'proj_1', review_round_id: 'round_1', status: 'queued', warnings: [],
    });

    render(<ProjectDetailPage project={project} />);
    await user.click(await screen.findByRole('tab', { name: /검수 #1/ }));
    await user.click(screen.getByRole('button', { name: '▶ 선택 라운드 검수 실행' }));

    await waitFor(() => {
      expect(apiMocks.triggerProofreadingRun).toHaveBeenCalledWith('proj_1', {
        review_round_id: 'round_1',
        enable_vlm: true,
        enable_ai_review: true,
      });
    });
  });

  it('blocks analysis until a round has body, plate/photo, and drawing versions', async () => {
    apiMocks.fetchReviewRounds.mockResolvedValue([
      { ...round(), plateVersionId: null, drawingVersionId: null },
    ]);
    render(<ProjectDetailPage project={project} />);

    const button = await screen.findByRole('button', { name: '▶ 선택 라운드 검수 실행' });
    expect(button).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('본문·도판/사진·도면 3종');
  });
});

describe('ProjectDetailPage ReviewRound lifecycle', () => {
  it('requires all three assets when creating the first round', async () => {
    const user = userEvent.setup();
    apiMocks.fetchReviewRounds.mockResolvedValue([]);
    apiMocks.createReviewRound.mockResolvedValue({ ...round(), status: 'draft' });
    render(<ProjectDetailPage project={project} />);

    await user.click(await screen.findByRole('button', { name: '+ 새 검수 라운드 생성' }));
    expect(screen.getByLabelText('이전 라운드 도판 / 사진 재사용')).toBeDisabled();
    expect(screen.getByLabelText('이전 라운드 도면 재사용')).toBeDisabled();
    expect(screen.getByLabelText('본문 문서')).toHaveValue('body_v1');
    expect(screen.getByLabelText('도판 / 사진 문서')).toHaveValue('plate_v1');
    expect(screen.getByLabelText('도면 문서')).toHaveValue('drawing_v1');

    await user.click(screen.getByRole('button', { name: '검수 라운드 생성' }));
    await waitFor(() => {
      expect(apiMocks.createReviewRound).toHaveBeenCalledWith('proj_1', expect.objectContaining({
        body_version_id: 'body_v1',
        plate_version_id: 'plate_v1',
        drawing_version_id: 'drawing_v1',
      }));
    });
  });

  it('reuses unchanged plate/photo and drawing assets in a later round', async () => {
    const user = userEvent.setup();
    apiMocks.fetchReviewRounds.mockResolvedValue([round('round_1', 1)]);
    apiMocks.createReviewRound.mockResolvedValue({ ...round('round_2', 2), status: 'draft' });
    render(<ProjectDetailPage project={project} />);

    await user.click(await screen.findByRole('button', { name: '+ 새 검수 라운드 생성' }));
    expect(screen.getByLabelText('이전 라운드 도판 / 사진 재사용')).toBeChecked();
    expect(screen.getByLabelText('이전 라운드 도면 재사용')).toBeChecked();
    await user.click(screen.getByRole('button', { name: '검수 라운드 생성' }));

    await waitFor(() => {
      expect(apiMocks.createReviewRound).toHaveBeenCalledWith('proj_1', expect.objectContaining({
        plate_version_id: 'plate_v1',
        drawing_version_id: 'drawing_v1',
      }));
    });
  });

  it('approves the selected round through the expert workflow', async () => {
    const user = userEvent.setup();
    apiMocks.fetchReviewRounds.mockResolvedValue([round()]);
    apiMocks.approveReviewRound.mockResolvedValue({ ...round(), status: 'approved', approvedAt: '2026-08-17T09:00:00Z' });
    render(<ProjectDetailPage project={project} />);

    await user.click(await screen.findByRole('button', { name: '✓ 검수 라운드 승인' }));
    await waitFor(() => expect(apiMocks.approveReviewRound).toHaveBeenCalledWith('proj_1', 'round_1'));
    expect(await screen.findByText('✓ 승인 완료 (Approved)')).toBeInTheDocument();
  });
});

describe('ProjectDetailPage operational UX', () => {
  it('supports batch upload without passing a user-selected revision stage', async () => {
    const user = userEvent.setup();
    apiMocks.uploadDocument
      .mockResolvedValueOnce({ documentVersionId: 'plate_v2', analysisRunId: 'ingest_1' })
      .mockResolvedValueOnce({ documentVersionId: 'drawing_v2', analysisRunId: 'ingest_2' });
    render(<ProjectDetailPage project={project} />);

    const input = screen.getByLabelText('원본 파일') as HTMLInputElement;
    expect(input.multiple).toBe(true);
    await user.upload(input, [
      new File(['x'], '도판-수정.pdf', { type: 'application/pdf' }),
      new File(['y'], '도면-수정.pdf', { type: 'application/pdf' }),
    ]);

    await waitFor(() => expect(apiMocks.uploadDocument).toHaveBeenCalledTimes(2));
    expect(apiMocks.uploadDocument).toHaveBeenNthCalledWith(1, 'proj_1', expect.any(File), 'plate_book');
    expect(apiMocks.uploadDocument).toHaveBeenNthCalledWith(2, 'proj_1', expect.any(File), 'drawing_book');
  });

  it('shows retry for a failed retryable ingest', async () => {
    const user = userEvent.setup();
    apiMocks.getProject.mockResolvedValue(makeDetail({
      analysisRuns: [{
        id: 'run_fail', status: 'failed', step: 'ingest', documentVersionId: 'body_v1',
        errorCode: 'conversion_error', retryable: true,
      }],
    }));
    apiMocks.retryAnalysisRun.mockResolvedValue({ analysisRunId: 'run_fail', status: 'queued' });
    render(<ProjectDetailPage project={project} />);

    await user.click(await screen.findByRole('button', { name: '재시도' }));
    await waitFor(() => expect(apiMocks.retryAnalysisRun).toHaveBeenCalledWith('proj_1', 'run_fail'));
  });

  it('uses backend RuleCategory values in the candidate filter', async () => {
    render(<ProjectDetailPage project={project} />);
    const category = await screen.findByLabelText('유형:');
    const values = within(category).getAllByRole('option').map((option) => option.getAttribute('value'));
    expect(values).toContain('figure_plate_table_photo_ref');
    expect(values).toContain('feature_or_artifact_id');
    expect(values).toContain('numeric_value');
    expect(values).not.toContain('plate_reference');
  });
});
