import { describe, expect, it } from 'vitest';

import { candidateIntentLabel } from './candidateIntent';


describe('candidateIntentLabel', () => {
  it.each([
    ['visual_reference_missing', '참조 누락'],
    ['visual_reference_blank_fill', '참조 빈칸'],
    ['visual_reference_ambiguous', '참조 후보 복수'],
    ['visual_reference_location_ambiguous', '참조 위치 확인 필요'],
    ['visual_reference_wrong_target', '기존 참조 불일치'],
  ])('maps %s to %s', (ruleName, expected) => {
    expect(candidateIntentLabel(ruleName)).toBe(expected);
  });

  it('returns null for ordinary rules', () => {
    expect(candidateIntentLabel('mention_claim')).toBeNull();
    expect(candidateIntentLabel(undefined)).toBeNull();
  });
});
