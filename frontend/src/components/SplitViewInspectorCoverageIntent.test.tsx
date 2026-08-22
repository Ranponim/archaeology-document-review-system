import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import type { CorrectionCandidate } from '../api';
import { SplitViewInspector } from './SplitViewInspector';


function candidate(ruleName: string, proposedText: string | null = '(도판 45)'): CorrectionCandidate {
  return {
    id: `cand-${ruleName}`,
    status: 'pending_review',
    rule_category: 'figure_plate_table_photo_ref',
    change_type: proposedText === null ? 'added' : 'modified',
    original_text: '6호 석관묘',
    proposed_text: proposedText,
    confidence: 1,
    evidence: {
      id: `ev-${ruleName}`,
      kind: 'rule_finding',
      rule_name: ruleName,
      source_sha256: 'body-sha',
      document_version_id: 'body-v1',
      page_id: 'body-v1-p1',
    },
  };
}


describe('SplitViewInspector visual coverage intent', () => {
  it('shows missing-reference intent for archaeologists', () => {
    render(
      <SplitViewInspector
        projectId="project-1"
        candidate={candidate('visual_reference_missing')}
        visualBundle={{} as never}
      />,
    );

    expect(screen.getByTestId('coverage-intent-label')).toHaveTextContent('참조 누락');
  });

  it('makes ambiguity explicitly manual and shows no fake replacement', () => {
    render(
      <SplitViewInspector
        projectId="project-1"
        candidate={candidate('visual_reference_ambiguous', null)}
        visualBundle={{} as never}
      />,
    );

    const label = screen.getByTestId('coverage-intent-label');
    expect(label).toHaveTextContent('참조 후보 복수');
    expect(label).toHaveTextContent('자동 번호 삽입 없음');
  });
});
