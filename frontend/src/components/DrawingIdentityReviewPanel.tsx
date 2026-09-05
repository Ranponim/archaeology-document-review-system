import { useEffect, useState } from 'react';

import {
  type DrawingReviewCandidate,
  type DrawingReviewCase,
  fetchDrawingReviews,
  resolveDrawingReview,
} from '../drawingReviewApi';
import './DrawingIdentityReviewPanel.css';

type Props = {
  projectId: string;
};

function publicationLabel(candidate: DrawingReviewCandidate): string {
  return candidate.publication_kind === 'illustration' ? '삽도' : '도면';
}

function CandidateImage({ candidate }: { candidate: DrawingReviewCandidate }) {
  if (!candidate.image_url) {
    return <div className="drawing-review-image-missing">이미지 없음</div>;
  }
  return (
    <img
      className="drawing-review-image"
      src={candidate.image_url}
      alt={`${publicationLabel(candidate)} ${candidate.number} 후보`}
    />
  );
}

export function DrawingIdentityReviewPanel({ projectId }: Props) {
  const [cases, setCases] = useState<DrawingReviewCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void fetchDrawingReviews(projectId)
      .then((rows) => {
        if (active) setCases(rows);
      })
      .catch((cause) => {
        if (active) setError(cause instanceof Error ? cause.message : 'server_error');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [projectId]);

  async function resolveCase(
    current: DrawingReviewCase,
    candidate: DrawingReviewCandidate | null,
  ) {
    if (submitting) return;
    const action = candidate
      ? candidate.candidate_id === current.codex_candidate_id
        ? 'approve'
        : 'choose'
      : 'none';
    setSubmitting(true);
    setError(null);
    try {
      await resolveDrawingReview(projectId, current.source_asset_id, {
        action,
        candidate_id: candidate?.candidate_id ?? null,
        reviewer: 'human',
      });
      setCases((rows) =>
        rows.filter((row) => row.source_asset_id !== current.source_asset_id),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'server_error');
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return <p>도면 검수 불러오는 중…</p>;
  }
  if (error && cases.length === 0) {
    return <p role="alert">{error}</p>;
  }
  if (cases.length === 0) {
    return <p>검수할 도면 없음</p>;
  }

  const current = cases[0];
  const confidence =
    current.codex_confidence == null
      ? null
      : Math.round(current.codex_confidence * 100);

  return (
    <div className="drawing-review-panel">
      {error && <p role="alert">{error}</p>}
      <div className="drawing-review-source">
        <div>
          <strong>{current.source_name}</strong>
          <p>{current.source_text}</p>
          {confidence != null && (
            <span className="drawing-review-codex">Codex {confidence}%</span>
          )}
          {current.codex_summary && <p>{current.codex_summary}</p>}
          <details>
            <summary>원본 ID</summary>
            <code>{current.source_asset_id}</code>
          </details>
        </div>
        {current.source_image_url ? (
          <img
            className="drawing-review-source-image"
            src={current.source_image_url}
            alt={`${current.source_name} 원본`}
          />
        ) : (
          <div className="drawing-review-image-missing">원본 이미지 없음</div>
        )}
      </div>

      <div className="drawing-review-candidates">
        {current.candidates.map((candidate) => {
          const isCodex = candidate.candidate_id === current.codex_candidate_id;
          const label = `${publicationLabel(candidate)} ${candidate.number}`;
          return (
            <article
              key={candidate.candidate_id}
              className={`drawing-review-candidate${isCodex ? ' codex-selected' : ''}`}
              data-testid={`drawing-candidate-${candidate.candidate_id}`}
              tabIndex={0}
            >
              <header>
                <strong>{label}</strong>
                {isCodex && <span>Codex 선택</span>}
              </header>
              <CandidateImage candidate={candidate} />
              <p>{candidate.caption}</p>
              <div className="drawing-review-chips" aria-label={`${label} 근거`}>
                {candidate.evidence_summary.map((item) => (
                  <span className="support" key={`support-${item}`}>{item}</span>
                ))}
                {candidate.contradiction_summary.map((item) => (
                  <span className="contradiction" key={`contradiction-${item}`}>{item}</span>
                ))}
              </div>
              <details>
                <summary>상세</summary>
                <p>local score: {candidate.local_score}</p>
                <code>{candidate.candidate_id}</code>
              </details>
              <button
                type="button"
                disabled={submitting}
                onClick={() => void resolveCase(current, candidate)}
              >
                {isCodex ? `${label} 승인` : `${label} 선택`}
              </button>
            </article>
          );
        })}
      </div>

      <div className="drawing-review-actions">
        <span>{cases.length}건 남음</span>
        <button
          type="button"
          disabled={submitting}
          onClick={() => void resolveCase(current, null)}
        >
          모두 아님
        </button>
      </div>
    </div>
  );
}
