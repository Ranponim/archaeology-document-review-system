import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import * as api from '../referenceCorpusApi';
import { ReferenceCorpusPanel } from './ReferenceCorpusPanel';


describe('ReferenceCorpusPanel', () => {
  it('shows plate PDF as the Adobe-free authority while retaining INDD as optional provenance', async () => {
    vi.spyOn(api, 'listReferenceCorpora').mockResolvedValue([]);
    render(<ReferenceCorpusPanel projectId="p1" />);

    expect(await screen.findByText('도판 PDF')).toBeInTheDocument();
    expect(screen.getByText('도판 INDD')).toBeInTheDocument();
    expect(screen.getByText('Links 사진')).toBeInTheDocument();
    expect(screen.getByText('도면 AI')).toBeInTheDocument();

    expect(screen.getByLabelText('도판 PDF 파일')).toHaveAttribute('accept', '.pdf,application/pdf');
    expect(screen.getByLabelText('도판 INDD 파일')).toHaveAttribute('accept', '.indd');
    expect(screen.getByLabelText('도면 AI 파일')).toHaveAttribute('accept', '.ai');
    expect(screen.getByText(/Adobe 없이.*도판 PDF.*AI.*Links/)).toBeInTheDocument();
  });

  it('creates a corpus, stages plate PDF with relative path, then builds it', async () => {
    vi.spyOn(api, 'listReferenceCorpora').mockResolvedValue([]);
    vi.spyOn(api, 'createReferenceCorpus').mockResolvedValue({
      id: 'c1', projectId: 'p1', revision: 1, status: 'staging', failureCode: null,
    });
    const upload = vi.spyOn(api, 'uploadReferenceCorpusSource').mockResolvedValue({
      id: 'a1', role: 'plate_pdf', originalName: 'plates.pdf', relativePath: 'plates.pdf', sha256: 'abc',
    });
    vi.spyOn(api, 'buildReferenceCorpus').mockResolvedValue({
      id: 'c1', projectId: 'p1', revision: 1, status: 'ready', failureCode: null,
    });

    render(<ReferenceCorpusPanel projectId="p1" />);
    fireEvent.click(await screen.findByRole('button', { name: '새 기준자료 구축' }));

    const input = screen.getByLabelText('도판 PDF 파일') as HTMLInputElement;
    await waitFor(() => expect(input).toBeEnabled());
    const pdf = new File(['pdf'], 'plates.pdf', { type: 'application/pdf' });
    fireEvent.change(input, { target: { files: [pdf] } });

    await waitFor(() => expect(upload).toHaveBeenCalledWith(
      'p1', 'c1', 'plate_pdf', pdf, 'plates.pdf',
    ));
    await waitFor(() => expect(screen.getByRole('button', { name: '기준 그래프 구축' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: '기준 그래프 구축' }));
    expect(await screen.findByText('READY')).toBeInTheDocument();
  });
});