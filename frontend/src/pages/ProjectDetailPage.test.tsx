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
  apiMocks.getProject.mockResolvedValue(makeDetail());
});

afterEach(() => {
  vi.useRealTimers();
});

describe('ProjectDetailPage upload form', () => {
  it('shows document kind and revision stage selectors before upload', () => {
    render(<ProjectDetailPage project={project} />);

    const kind = screen.getByLabelText('문서 종류');
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