const VISUAL_REFERENCE_INTENT_LABELS: Record<string, string> = {
  visual_reference_missing: '참조 누락',
  visual_reference_blank_fill: '참조 빈칸',
  visual_reference_ambiguous: '참조 후보 복수',
  visual_reference_location_ambiguous: '참조 위치 확인 필요',
  visual_reference_wrong_target: '기존 참조 불일치',
};

export function candidateIntentLabel(ruleName: string | null | undefined): string | null {
  if (!ruleName) return null;
  return VISUAL_REFERENCE_INTENT_LABELS[ruleName] ?? null;
}
