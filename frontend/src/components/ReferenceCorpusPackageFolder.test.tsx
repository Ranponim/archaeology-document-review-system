import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import * as api from '../referenceCorpusApi';
import { ReferenceCorpusPanel } from './ReferenceCorpusPanel';


function withRelativePath(file: File, relativePath: string): File {
  Object.defineProperty(file, 'webkitRelativePath', {
    configurable: true,
    value: relativePath,
  });
  return file;
}


describe('ReferenceCorpus path-preserving package upload', () => {
  it('uploads INDD and Links from one selected folder with their browser relative paths', async () => {
    vi.spyOn(api, 'listReferenceCorpora').mockResolvedValue([]);
    vi.spyOn(api, 'createReferenceCorpus').mockResolvedValue({
      id: 'c1', projectId: 'p1', revision: 1, status: 'staging', failureCode: null,
    });
    const upload = vi.spyOn(api, 'uploadReferenceCorpusSource').mockImplementation(
      async (_projectId, _corpusId, role, file, relativePath) => ({
        id: `${role}-${file.name}`,
        role,
        originalName: file.name,
        relativePath: relativePath ?? file.name,
        sha256: 'sha',
      }),
    );

    render(<ReferenceCorpusPanel projectId="p1" />);
    fireEvent.click(await screen.findByRole('button', { name: '새 기준자료 구축' }));

    const packageInput = screen.getByLabelText('도판 패키지 폴더') as HTMLInputElement;
    await waitFor(() => expect(packageInput).toBeEnabled());
    expect(packageInput).toHaveAttribute('webkitdirectory');
    expect(packageInput).toHaveAttribute('multiple');

    const indd = withRelativePath(
      new File(['indd'], 'book.indd', { type: 'application/octet-stream' }),
      'Publication/book.indd',
    );
    const photo = withRelativePath(
      new File(['jpeg'], 'photo.jpg', { type: 'image/jpeg' }),
      'Publication/Links/photo.jpg',
    );
    const ignored = withRelativePath(
      new File(['notes'], 'README.txt', { type: 'text/plain' }),
      'Publication/README.txt',
    );

    fireEvent.change(packageInput, { target: { files: [indd, photo, ignored] } });

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    expect(upload).toHaveBeenCalledWith(
      'p1', 'c1', 'plate_layout', indd, 'Publication/book.indd',
    );
    expect(upload).toHaveBeenCalledWith(
      'p1', 'c1', 'plate_link', photo, 'Publication/Links/photo.jpg',
    );
    expect(upload).not.toHaveBeenCalledWith(
      expect.anything(), expect.anything(), expect.anything(), ignored, expect.anything(),
    );
  });

  it('preserves AI relative path when available and falls back to filename otherwise', async () => {
    vi.spyOn(api, 'listReferenceCorpora').mockResolvedValue([]);
    vi.spyOn(api, 'createReferenceCorpus').mockResolvedValue({
      id: 'c1', projectId: 'p1', revision: 1, status: 'staging', failureCode: null,
    });
    const upload = vi.spyOn(api, 'uploadReferenceCorpusSource').mockResolvedValue({
      id: 'a1', role: 'drawing_source', originalName: 'plan.ai', relativePath: 'Drawings/plan.ai', sha256: 'sha',
    });

    render(<ReferenceCorpusPanel projectId="p1" />);
    fireEvent.click(await screen.findByRole('button', { name: '새 기준자료 구축' }));
    const aiInput = screen.getByLabelText('도면 AI 파일') as HTMLInputElement;
    await waitFor(() => expect(aiInput).toBeEnabled());

    const ai = withRelativePath(
      new File(['ai'], 'plan.ai', { type: 'application/octet-stream' }),
      'Drawings/plan.ai',
    );
    fireEvent.change(aiInput, { target: { files: [ai] } });

    await waitFor(() => expect(upload).toHaveBeenCalledWith(
      'p1', 'c1', 'drawing_source', ai, 'Drawings/plan.ai',
    ));
  });
});
