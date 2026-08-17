import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Project, ProjectDetail } from '../api';
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
  fetchReviewRound: vi.fn(),
  createReviewRound: vi.fn(),
  approveReviewRound: vi.fn(),
}));

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return {
    ...actual,
    ...apiMocks,
  };
});

const project: Project = { id: 'proj_1', name: '산노리', internalCode: null };

function makeDetail(overrides: Partial<ProjectDetail> = {}): ProjectDetail {
  return {
    ...project,
    documents: [
      { id: 'doc_1', projectId: 'proj_1', kind: 'report_body', title: '본문' },
      { id: 'doc_2', projectId: 'proj_1', kind: 'plate_book', title: '도판' },
      { id: 'doc_3', projectId: 'proj_1', kind: 'drawing_book', title: '도면' },
    ],
    documentVersions: [
      {
        id: 'ver_body_1',
        documentId: 'doc_1',
        originalName: '본문-1차.pdf',
        mimeType: 'application/pdf',
        sizeBytes: 2048,
        stage: '1차',
        kind: 'report_body',
      },
      {
        id: 'ver_plate_1',
        documentId: 'doc_2',
        originalName: '도판.pdf',
        mimeType: 'application/pdf',
        sizeBytes: 1024,
        stage: '1차',
        kind: 'plate_book',
      },
      {
        id: 'ver_draw_1',
        documentId: 'doc_3',
        originalName: '도면.pdf',
        mimeType: 'application/pdf',
        sizeBytes: 1024,
        stage: '1차',
        kind: 'drawing_book',
      },
    ],
    analysisRuns: [],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.fetchCandidates.mockResolvedValue({ total: 0, candidates: [] });
  apiMocks.fetchMetrics.mockResolvedValue({});
  apiMocks.fetchTraceability.mockResolvedValue({});
  apiMocks.fetchVisualBundle.mockResolvedValue({ candidateId: 'x' });
  apiMocks.getProject.mockResolvedValue(makeDetail());
  apiMocks.fetchReviewRounds.mockResolvedValue([]);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('ProjectDetailPage upload form', () => {
  it('shows document kind and revision stage selectors before upload', async () => {
    render(<ProjectDetailPage project={project} />);

    const kind = await screen.findByLabelText('문서 종류');
    expect(kind).toBeInTheDocument();
    expect(within(kind).getByRole('option', { name: '본문' })).toBeInTheDocument();
    expect(within(kind).getByRole('option', { name: '도판' })).toBeInTheDocument();
    expect(within(kind).getByRole('option', { name: '도면' })).toBeInTheDocument();

    const stage = screen.getByLabelText('교정 단계');
    expect(within(stage).getByRole('option', { name: '1차' })).toBeInTheDocument();
    expect(within(stage).getByRole('option', { name: '2차' })).toBeInTheDocument();
    expect(within(stage).getByRole('option', { name: '3차' })).toBeInTheDocument();
    expect(within(stage).getByRole('option', { name: '최종' })).toBeInTheDocument();
  });
});

describe('ProjectDetailPage run form', () => {
  it('lists real uploaded version ids and has no path input', async () => {
    render(<ProjectDetailPage project={project} />);

    const bodySelect = await screen.findByLabelText('본문 버전');
    const bodyValues = within(bodySelect)
      .getAllByRole('option')
      .map((o) => o.getAttribute('value'));
    expect(bodyValues).toContain('ver_body_1');

    const plateSelect = screen.getByLabelText('도판 버전');
    const plateValues = within(plateSelect)
      .getAllByRole('option')
      .map((o) => o.getAttribute('value'));
    expect(plateValues).toContain('ver_plate_1');

    const drawSelect = screen.getByLabelText('도면 버전');
    const drawValues = within(drawSelect)
      .getAllByRole('option')
      .map((o) => o.getAttribute('value'));
    expect(drawValues).toContain('ver_draw_1');

    const runForm = screen.getByRole('button', { name: /새 검수 실행/ }).closest('form');
    expect(runForm).not.toBeNull();
    expect(within(runForm as HTMLElement).queryByRole('textbox')).toBeNull();
  });

  it('submits version ids and shows queued state', async () => {
    const user = userEvent.setup();
    apiMocks.triggerProofreadingRun.mockResolvedValue({
      run_id: 'run_1',
      status: 'queued',
      warnings: [],
    });
    render(<ProjectDetailPage project={project} />);

    await screen.findByLabelText('본문 버전');
    await user.selectOptions(screen.getByLabelText('도판 버전'), 'ver_plate_1');
    await user.click(screen.getByRole('button', { name: /새 검수 실행/ }));

    await waitFor(() => {
      expect(apiMocks.triggerProofreadingRun).toHaveBeenCalledWith(
        'proj_1',
        expect.objectContaining({
          body_version_id: 'ver_body_1',
          plate_version_id: 'ver_plate_1',
          drawing_version_id: null,
        }),
      );
    });
    expect(await screen.findByText('queued')).toBeInTheDocument();
  });

  it('polls run status until completed', async () => {
    vi.useFakeTimers();
    let call = 0;
    apiMocks.getProject.mockImplementation(async () => {
      call += 1;
      if (call < 3) return makeDetail();
      return makeDetail({
        analysisRuns: [
          {
            id: 'run_1',
            status: 'completed',
            step: 'analysis',
            documentVersionId: 'ver_body_1',
            errorCode: null,
            retryable: false,
          },
        ],
      });
    });
    apiMocks.triggerProofreadingRun.mockResolvedValue({
      run_id: 'run_1',
      status: 'queued',
      warnings: [],
    });
    render(<ProjectDetailPage project={project} />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    fireEvent.click(screen.getByRole('button', { name: /새 검수 실행/ }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText('queued')).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getAllByText('completed').length).toBeGreaterThan(0);
  });

  it('displays warnings from the run response', async () => {
    const user = userEvent.setup();
    apiMocks.triggerProofreadingRun.mockResolvedValue({
      run_id: 'run_1',
      status: 'queued',
      warnings: ['도판 버전이 지정되지 않았습니다'],
    });
    render(<ProjectDetailPage project={project} />);

    await screen.findByLabelText('본문 버전');
    await user.click(screen.getByRole('button', { name: /새 검수 실행/ }));

    expect(
      await screen.findByText('도판 버전이 지정되지 않았습니다'),
    ).toBeInTheDocument();
  });
});

describe('ProjectDetailPage document kind after reload', () => {
  it('maps DocumentVersion.documentId -> Document.kind so kinds survive reload', async () => {
    apiMocks.getProject.mockResolvedValue(
      makeDetail({
        documents: [
          { id: 'doc_1', projectId: 'proj_1', kind: 'report_body', title: '본문' },
          { id: 'doc_2', projectId: 'proj_1', kind: 'plate_book', title: '도판' },
          { id: 'doc_3', projectId: 'proj_1', kind: 'drawing_book', title: '도면' },
        ],
        documentVersions: [
          {
            id: 'ver_body_1',
            documentId: 'doc_1',
            originalName: '본문-1차.pdf',
            mimeType: 'application/pdf',
            sizeBytes: 2048,
            stage: '1차',
          },
          {
            id: 'ver_plate_1',
            documentId: 'doc_2',
            originalName: '도판.pdf',
            mimeType: 'application/pdf',
            sizeBytes: 1024,
            stage: '1차',
          },
          {
            id: 'ver_draw_1',
            documentId: 'doc_3',
            originalName: '도면.pdf',
            mimeType: 'application/pdf',
            sizeBytes: 1024,
            stage: '1차',
          },
        ],
      }),
    );
    render(<ProjectDetailPage project={project} />);

    const bodySelect = await screen.findByLabelText('본문 버전');
    const bodyValues = within(bodySelect)
      .getAllByRole('option')
      .map((o) => o.getAttribute('value'));
    expect(bodyValues).toContain('ver_body_1');
    expect(bodyValues).not.toContain('ver_plate_1');
    expect(bodyValues).not.toContain('ver_draw_1');

    const plateSelect = screen.getByLabelText('도판 버전');
    const plateValues = within(plateSelect)
      .getAllByRole('option')
      .map((o) => o.getAttribute('value'));
    expect(plateValues).toContain('ver_plate_1');
    expect(plateValues).not.toContain('ver_body_1');

    const drawSelect = screen.getByLabelText('도면 버전');
    const drawValues = within(drawSelect)
      .getAllByRole('option')
      .map((o) => o.getAttribute('value'));
    expect(drawValues).toContain('ver_draw_1');
    expect(drawValues).not.toContain('ver_body_1');
  });

  it('sends version_stage from the selected body version', async () => {
    const user = userEvent.setup();
    apiMocks.getProject.mockResolvedValue(
      makeDetail({
        documentVersions: [
          {
            id: 'ver_body_1',
            documentId: 'doc_1',
            originalName: '본문-1차.pdf',
            mimeType: 'application/pdf',
            sizeBytes: 2048,
            stage: '1차',
            kind: 'report_body',
          },
          {
            id: 'ver_body_3',
            documentId: 'doc_1',
            originalName: '본문-3차.pdf',
            mimeType: 'application/pdf',
            sizeBytes: 4096,
            stage: '3차',
            kind: 'report_body',
          },
        ],
      }),
    );
    apiMocks.triggerProofreadingRun.mockResolvedValue({
      run_id: 'run_1',
      status: 'queued',
      warnings: [],
    });
    render(<ProjectDetailPage project={project} />);

    const bodySelect = await screen.findByLabelText('본문 버전');
    await user.selectOptions(bodySelect, 'ver_body_3');
    await user.click(screen.getByRole('button', { name: /새 검수 실행/ }));

    await waitFor(() => {
      expect(apiMocks.triggerProofreadingRun).toHaveBeenCalledWith(
        'proj_1',
        expect.objectContaining({
          body_version_id: 'ver_body_3',
          version_stage: '3차',
        }),
      );
    });
  });
});

describe('ProjectDetailPage retry + severity honesty', () => {
  it('shows a retry button for a retryable failed run and calls the retry endpoint', async () => {
    const user = userEvent.setup();
    apiMocks.getProject.mockResolvedValue(
      makeDetail({
        analysisRuns: [
          {
            id: 'run_fail',
            status: 'failed',
            step: 'ingest',
            documentVersionId: 'ver_body_1',
            errorCode: 'conversion_error',
            retryable: true,
          },
        ],
      }),
    );
    apiMocks.retryAnalysisRun.mockResolvedValue({
      analysis_run_id: 'run_fail',
      status: 'queued',
    });
    render(<ProjectDetailPage project={project} />);

    const retryBtn = await screen.findByRole('button', { name: '재시도' });
    await user.click(retryBtn);

    await waitFor(() => {
      expect(apiMocks.retryAnalysisRun).toHaveBeenCalledWith('proj_1', 'run_fail');
    });
  });

  it('does not present a silent severity filter (removed because the backend ignores it)', async () => {
    render(<ProjectDetailPage project={project} />);
    await screen.findByLabelText('본문 버전');

    expect(screen.queryByLabelText('중요도:')).toBeNull();
    expect(screen.queryByLabelText('중요도')).toBeNull();
    expect(screen.queryByRole('option', { name: '높음 (High)' })).toBeNull();
  });
});

describe('ProjectDetailPage Review Round Management', () => {
  it('fetches and displays review rounds with sequence and status badges', async () => {
    apiMocks.fetchReviewRounds.mockResolvedValue([
      {
        id: 'round_1',
        projectId: 'proj_1',
        sequence: 1,
        status: 'approved',
        bodyVersionId: 'ver_body_1',
        plateVersionId: 'ver_plate_1',
        drawingVersionId: 'ver_draw_1',
        notes: '1차 완독 검수 완료',
      },
      {
        id: 'round_2',
        projectId: 'proj_1',
        sequence: 2,
        status: 'reviewing',
        bodyVersionId: 'ver_body_2',
        plateVersionId: 'ver_plate_1',
        drawingVersionId: 'ver_draw_1',
        notes: '2차 수정본 검수 중',
      },
    ]);

    render(<ProjectDetailPage project={project} />);

    expect(await screen.findByText('1차 검수')).toBeInTheDocument();
    expect(screen.getByText('2차 검수')).toBeInTheDocument();
    expect(screen.getAllByText('검수중').length).toBeGreaterThan(0);
  });

  it('creates a new review round with asset reuse checkboxes and notes', async () => {
    const user = userEvent.setup();
    apiMocks.fetchReviewRounds.mockResolvedValue([
      {
        id: 'round_1',
        projectId: 'proj_1',
        sequence: 1,
        status: 'approved',
        bodyVersionId: 'ver_body_1',
        plateVersionId: 'ver_plate_1',
        drawingVersionId: 'ver_draw_1',
      },
    ]);
    apiMocks.createReviewRound.mockResolvedValue({
      id: 'round_2',
      projectId: 'proj_1',
      sequence: 2,
      status: 'draft',
      bodyVersionId: 'ver_body_1',
      plateVersionId: 'ver_plate_1',
      drawingVersionId: 'ver_draw_1',
      notes: '2차 도판 재사용 검수',
    });

    render(<ProjectDetailPage project={project} />);

    const createBtn = await screen.findByRole('button', { name: '+ 새 검수 라운드 생성' });
    await user.click(createBtn);

    expect(screen.getByText('새 검수 라운드 생성')).toBeInTheDocument();
    expect(screen.getByLabelText(/이전 도판 재사용/)).toBeChecked();
    expect(screen.getByLabelText(/이전 도면 재사용/)).toBeChecked();

    const notesInput = screen.getByLabelText(/검수 차수 메모/);
    await user.type(notesInput, '2차 도판 재사용 검수');

    const submitBtn = screen.getByRole('button', { name: '검수 라운드 생성' });
    await user.click(submitBtn);

    await waitFor(() => {
      expect(apiMocks.createReviewRound).toHaveBeenCalledWith(
        'proj_1',
        expect.objectContaining({
          body_version_id: 'ver_body_1',
          plate_version_id: 'ver_plate_1',
          drawing_version_id: 'ver_draw_1',
          notes: '2차 도판 재사용 검수',
        }),
      );
    });
  });

  it('approves an active review round when the approve button is clicked', async () => {
    const user = userEvent.setup();
    apiMocks.fetchReviewRounds.mockResolvedValue([
      {
        id: 'round_1',
        projectId: 'proj_1',
        sequence: 1,
        status: 'reviewing',
        bodyVersionId: 'ver_body_1',
        plateVersionId: 'ver_plate_1',
        drawingVersionId: 'ver_draw_1',
      },
    ]);
    apiMocks.approveReviewRound.mockResolvedValue({
      id: 'round_1',
      projectId: 'proj_1',
      sequence: 1,
      status: 'approved',
      approved_at: '2026-08-17T16:00:00Z',
    });

    render(<ProjectDetailPage project={project} />);

    const approveBtn = await screen.findByRole('button', { name: '✓ 검수 라운드 승인' });
    await user.click(approveBtn);

    await waitFor(() => {
      expect(apiMocks.approveReviewRound).toHaveBeenCalledWith('proj_1', 'round_1');
    });
    expect(await screen.findByText('✓ 승인 완료 (Approved)')).toBeInTheDocument();
  });
});

describe('ProjectDetailPage Batch Upload & Pipeline Progress', () => {
  it('supports multi-file selection for batch upload', async () => {
    const user = userEvent.setup();
    let uploadCount = 0;
    apiMocks.uploadDocument.mockImplementation(async () => {
      uploadCount += 1;
      return {
        documentVersionId: `ver_batch_${uploadCount}`,
        analysisRunId: `run_batch_${uploadCount}`,
      };
    });

    render(<ProjectDetailPage project={project} />);

    const fileInput = screen.getByLabelText('원본 파일') as HTMLInputElement;
    expect(fileInput.multiple).toBe(true);

    const file1 = new File(['dummy content 1'], '도판-일괄.pdf', { type: 'application/pdf' });
    const file2 = new File(['dummy content 2'], '도면-일괄.pdf', { type: 'application/pdf' });

    await user.upload(fileInput, [file1, file2]);

    await waitFor(() => {
      expect(apiMocks.uploadDocument).toHaveBeenCalledTimes(2);
    });
  });

  it('renders pipeline stage progress indicators for active analysis runs', async () => {
    apiMocks.getProject.mockResolvedValue(
      makeDetail({
        analysisRuns: [
          {
            id: 'run_prog_1',
            status: 'running',
            step: 'ingest',
            documentVersionId: 'ver_body_1',
            errorCode: null,
            retryable: false,
            progressStage: '파싱 중',
            currentPage: 5,
            totalPages: 10,
          },
        ],
      }),
    );

    render(<ProjectDetailPage project={project} />);

    expect(await screen.findByText(/5 \/ 10 페이지/)).toBeInTheDocument();
    expect(screen.getAllByText(/파싱 중/).length).toBeGreaterThan(0);
    expect(screen.getAllByText('엔티티 추출 중').length).toBeGreaterThan(0);
    expect(screen.getAllByText('시각 에셋 대조 중').length).toBeGreaterThan(0);
  });
});