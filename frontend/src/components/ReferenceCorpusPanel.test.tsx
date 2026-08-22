import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import * as api from '../referenceCorpusApi';
import { ReferenceCorpusPanel } from './ReferenceCorpusPanel';


describe('ReferenceCorpusPanel', () => {
  it('shows INDD, linked-photo, and AI selectors without visual PDF authority', async () => {
    vi.spyOn(api, 'listReferenceCorpora').mockResolvedValue([]);
    render(<ReferenceCorpusPanel projectId="p1" />);

    expect(await screen.findByText('도판 INDD')).toBeInTheDocument();
    expect(screen.getByText('Links 사진')).toBeInTheDocument();
    expect(screen.getByText('도면 AI')).toBeInTheDocument();
    expect(screen.queryByText(/도판 PDF|도면 PDF/)).not.toBeInTheDocument();

    expect(screen.getByLabelText('도판 INDD 파일')).toHaveAttribute('accept', '.indd');
    expect(screen.getByLabelText('도면 AI 파일')).toHaveAttribute('accept', '.ai');
  });

  it('creates a corpus, stages source roles, then builds it', async () => {
    vi.spyOn(api, 'listReferenceCorpora').mockResolvedValue([]);
    vi.spyOn(api, 'createReferenceCorpus').mockResolvedValue({
      id: 'c1', projectId: 'p1', revision: 1, status: 'staging', failureCode: null,
    });
    const upload = vi.spyOn(api, 'uploadReferenceCorpusSource').mockResolvedValue({
      id: 'a1', role: 'plate_layout', originalName: 'plates.indd', sha256: 'abc',
    });
    vi.spyOn(api, 'buildReferenceCorpus').mockResolvedValue({
      id: 'c1', projectId: 'p1', revision: 1, status: 'ready', failureCode: null,
    });

    render(<ReferenceCorpusPanel projectId="p1" />);
    fireEvent.click(await screen.findByRole('button', { name: '새 기준자료 구축' }));

    const input = screen.getByLabelText('도판 INDD 파일') as HTMLInputElement;
    await waitFor(() => expect(input).toBeEnabled());
    fireEvent.change(input, { target: { files: [new File(['x'], 'plates.indd')] } });

    await waitFor(() => expect(upload).toHaveBeenCalledWith('p1', 'c1', 'plate_layout', expect.any(File)));
    await waitFor(() => expect(screen.getByRole('button', { name: '기준 그래프 구축' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: '기준 그래프 구축' }));
    expect(await screen.findByText('READY')).toBeInTheDocument();
  });
});
