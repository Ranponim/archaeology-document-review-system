import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import * as api from '../api';
import { ProjectsPage } from './ProjectsPage';

describe('ProjectsPage project metadata', () => {
  it('renders backend project order and creation timestamps without client re-sort', async () => {
    vi.spyOn(api, 'fetchProjects').mockResolvedValue([
      {
        id: 'newer',
        name: '최근 프로젝트',
        internalCode: null,
        createdAt: '2026-08-18T01:00:00Z',
        updatedAt: '2026-08-18T02:00:00Z',
      },
      {
        id: 'legacy',
        name: '과거 프로젝트',
        internalCode: null,
        createdAt: null,
        updatedAt: null,
      },
    ] as any);

    render(<ProjectsPage onCreated={() => undefined} onSelect={() => undefined} />);

    const newer = await screen.findByText('최근 프로젝트');
    const legacy = await screen.findByText('과거 프로젝트');
    expect(newer.compareDocumentPosition(legacy) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText(/2026/)).toBeInTheDocument();
    expect(screen.getByText('생성일 기록 없음')).toBeInTheDocument();
  });
});
