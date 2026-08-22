import type {
  CandidateVisualBundle,
  CorrectionCandidate,
  Evidence,
  ReviewDecision,
  TraceabilityResponse,
} from '../api';
import { candidateIntentLabel } from '../candidateIntent';
import { SplitViewInspector as BaseSplitViewInspector } from './SplitViewInspectorBase';

type Props = {
  projectId: string;
  candidate: CorrectionCandidate;
  traceability?: TraceabilityResponse | null;
  visualBundle?: CandidateVisualBundle | null;
  onDecisionSubmitted?: (decision: ReviewDecision) => void;
};

function evidenceList(candidate: CorrectionCandidate, traceability?: TraceabilityResponse | null): Evidence[] {
  const traceEvidence = Array.isArray(traceability?.evidence)
    ? traceability.evidence
    : traceability?.evidence
      ? [traceability.evidence]
      : [];
  return [
    ...(candidate.evidence ? [candidate.evidence] : []),
    ...(candidate.evidences ?? []),
    ...traceEvidence,
  ];
}

function visualCoverageRuleName(
  candidate: CorrectionCandidate,
  traceability?: TraceabilityResponse | null,
): string | null {
  for (const evidence of evidenceList(candidate, traceability)) {
    const ruleName = evidence.rule_name ?? evidence.ruleName ?? null;
    if (candidateIntentLabel(ruleName)) return ruleName;
  }
  return null;
}

export function SplitViewInspector(props: Props) {
  const ruleName = visualCoverageRuleName(props.candidate, props.traceability);
  const intentLabel = candidateIntentLabel(ruleName);

  return (
    <>
      {intentLabel && (
        <div
          className="comparison-grounding-banner coverage-intent-banner"
          data-testid="coverage-intent-label"
          role="note"
        >
          <strong>{intentLabel}</strong>
          {ruleName === 'visual_reference_ambiguous' ||
          ruleName === 'visual_reference_location_ambiguous' ? (
            <span className="comparison-warning"> · 자동 번호 삽입 없음 — 고고학자 확인 필요</span>
          ) : null}
        </div>
      )}
      <BaseSplitViewInspector {...props} />
    </>
  );
}
