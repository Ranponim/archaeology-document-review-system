import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import * as api from '../api';
import { ProjectsPage } from './ProjectsPage';

const projects = [
  {
    id: 'newer',
    name: '최근 프로젝트',
    internalCode: 'NONSAN-001',
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
];

afterEach(() => vi.restoreAllMocks());

describe('ProjectsPage project metadata', () => {
  it('renders backend project order and creation timestamps without client re-sort', async () => {
    vi.spyOn(api, 'fetchProjects').mockResolvedValue(projects as any);

    render(<ProjectsPage onCreated={() => undefined} onSelect={() => undefined} />);

    const newer = await screen.findByText('최근 프로젝트');
    const legacy = await screen.findByText('과거 프로젝트');
    expect(newer.compareDocumentPosition(legacy) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText(/2026/)).toBeInTheDocument();
    expect(screen.getByText('생성일 기록 없음')).toBeInTheDocument();
  });

  it('uses semantic base-state classes for visible cards and actions', async () => {
    vi.spyOn(api, 'fetchProjects').mockResolvedValue(projects as any);

    const { container } = render(
      <ProjectsPage onCreated={() => undefined} onSelect={() => undefined} />,
    );

    await screen.findByText('최근 프로젝트');
    expect(container.querySelector('.projects-header-row')).not.toBeNull();
    expect(container.querySelector('.project-list')).not.toBeNull();
    const cards = container.querySelectorAll('.project-card-item');
    expect(cards).toHaveLength(2);
    expect(container.querySelectorAll('.project-card-title')).toHaveLength(2);
    expect(container.querySelectorAll('.project-card-meta')).toHaveLength(2);
    expect(container.querySelectorAll('.project-created-at')).toHaveLength(2);
    expect(container.querySelectorAll('.project-card-open')).toHaveLength(2);

    const refresh = screen.getByRole('button', { name: '목록 새로고침' });
    expect(refresh).toHaveClass('secondary-button');
    expect(screen.getAllByRole('button', { name: /프로젝트 열기/ })).toHaveLength(2);

    // Visibility-critical color/background/border belongs to CSS classes, not
    // per-card inline styling that can disappear under hover/theme overrides.
    for (const card of cards) {
      const style = card.getAttribute('style') ?? '';
      expect(style).not.toMatch(/background|border|color/i);
    }
  });
});
