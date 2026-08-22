// @ts-expect-error Vitest runs in Node; this frontend package intentionally omits @types/node.
import { readFileSync } from 'node:fs';

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import * as api from '../projectStructureApi';
import { ProjectStructureExplorer } from './ProjectStructureExplorer';

const projectStructureCss = readFileSync(
  new URL('../project-structure.css', import.meta.url),
  'utf8',
);

const root = {
  projectId: 'p1',
  root: {
    id: 'p1', nodeType: 'project', label: '논산 산노리', sourceSystem: 'neo4j',
    expandable: true, childCount: 3, badges: [], details: {}, relationships: [],
  },
  groups: [
    { id: 'material:report_body', nodeType: 'material_group', label: '본문', sourceSystem: 'derived_group', expandable: true, childCount: 2, badges: ['파일 2'], details: { kind: 'report_body' }, relationships: [] },
    { id: 'material:plate_book', nodeType: 'material_group', label: '도판 / 사진', sourceSystem: 'derived_group', expandable: true, childCount: 1, badges: ['도판 89'], details: { kind: 'plate_book' }, relationships: [] },
    { id: 'material:drawing_book', nodeType: 'material_group', label: '도면', sourceSystem: 'derived_group', expandable: true, childCount: 1, badges: ['도면 59'], details: { kind: 'drawing_book' }, relationships: [] },
    { id: 'review-rounds', nodeType: 'review_round_group', label: '검수 세트', sourceSystem: 'derived_group', expandable: true, childCount: 2, badges: [], details: {}, relationships: [] },
    { id: 'archaeology-objects', nodeType: 'archaeology_object_group', label: '고고학 객체', sourceSystem: 'derived_group', expandable: true, childCount: 4, badges: [], details: {}, relationships: [] },
  ],
};

function cssBlock(selector: string): string {
  const selectorIndex = projectStructureCss.indexOf(selector);
  expect(selectorIndex, `missing selector ${selector}`).toBeGreaterThanOrEqual(0);
  const open = projectStructureCss.indexOf('{', selectorIndex);
  const close = projectStructureCss.indexOf('}', open + 1);
  expect(open, `missing declaration start for ${selector}`).toBeGreaterThan(selectorIndex);
  expect(close, `missing declaration end for ${selector}`).toBeGreaterThan(open);
  return projectStructureCss.slice(open + 1, close);
}

describe('ProjectStructureExplorer', () => {
  it('loads only root first and fetches children on expansion', async () => {
    vi.spyOn(api, 'fetchProjectStructure').mockResolvedValue(root as any);
    const children = vi.spyOn(api, 'fetchProjectStructureChildren').mockResolvedValue({
      items: [{ id: 'doc-body', nodeType: 'document', label: '보고서 본문', sourceSystem: 'neo4j', expandable: true, childCount: 2, badges: [], details: {}, relationships: [] }],
      offset: 0, limit: 50, total: 1, hasMore: false,
    } as any);
    vi.spyOn(api, 'fetchProjectStructureNode').mockResolvedValue(root.groups[0] as any);

    render(<ProjectStructureExplorer projectId="p1" />);
    expect(await screen.findByText('본문')).toBeInTheDocument();
    expect(children).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /본문/ }));
    await waitFor(() => expect(children).toHaveBeenCalledWith('p1', 'material_group', 'material:report_body', 0, 50));
    expect(await screen.findByText('보고서 본문')).toBeInTheDocument();
  });

  it('is read-only and shows exact graph relationship details', async () => {
    vi.spyOn(api, 'fetchProjectStructure').mockResolvedValue(root as any);
    vi.spyOn(api, 'fetchProjectStructureNode').mockResolvedValue({
      id: 'ref45', nodeType: 'reference', label: '도판 45', sourceSystem: 'neo4j', expandable: false, childCount: 0,
      badges: [], details: { refType: 'plate', number: '45' },
      relationships: [{ type: 'RESOLVES_TO', direction: 'out', target: { id: 'plate45', nodeType: 'plate', label: '【도판 45】' } }],
    } as any);
    vi.spyOn(api, 'fetchProjectStructureChildren').mockResolvedValue({ items: [], offset: 0, limit: 50, total: 0, hasMore: false } as any);

    render(<ProjectStructureExplorer projectId="p1" initialSelection={{ nodeType: 'reference', id: 'ref45' }} />);
    const semanticRelationship = await screen.findByText('인용 대상 연결');
    expect(semanticRelationship).toBeInTheDocument();
    expect(semanticRelationship).toHaveAttribute('title', 'RESOLVES_TO');
    expect(screen.getByText('【도판 45】')).toBeInTheDocument();
    expect(screen.queryByText(/삭제|이동|연결 변경|rename/i)).not.toBeInTheDocument();
  });

  it('gives every light project-structure button an explicit readable foreground', () => {
    const selectors = [
      '.project-mode-tab',
      '.project-mode-back',
      '.structure-refresh',
      '.structure-more-button',
    ];

    for (const selector of selectors) {
      const declarations = cssBlock(selector);
      expect(declarations, `${selector} must override global white button text`).toMatch(
        /color:\s*#[0-9a-f]{3,6}\s*;/i,
      );
    }
  });
});
