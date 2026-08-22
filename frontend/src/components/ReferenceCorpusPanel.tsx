import { ChangeEvent, useEffect, useMemo, useState } from 'react';

import {
  type ReferenceCorpus,
  type ReferenceCorpusSourceRole,
  buildReferenceCorpus,
  createReferenceCorpus,
  listReferenceCorpora,
  uploadReferenceCorpusSource,
} from '../referenceCorpusApi';
import './reference-corpus-panel.css';


type Props = {
  projectId: string;
  onReadyCorpusChange?: (corpus: ReferenceCorpus | null) => void;
};

type SourceCounts = Record<ReferenceCorpusSourceRole, number>;

const EMPTY_COUNTS: SourceCounts = {
  plate_layout: 0,
  plate_link: 0,
  drawing_source: 0,
};

function latestCorpus(items: ReferenceCorpus[]): ReferenceCorpus | null {
  if (!items.length) return null;
  return [...items].sort((a, b) => b.revision - a.revision)[0];
}

function statusLabel(status: ReferenceCorpus['status'] | undefined): string {
  return status ? status.toUpperCase() : '없음';
}

export function ReferenceCorpusPanel({ projectId, onReadyCorpusChange }: Props) {
  const [corpora, setCorpora] = useState<ReferenceCorpus[]>([]);
  const [selected, setSelected] = useState<ReferenceCorpus | null>(null);
  const [sourceCounts, setSourceCounts] = useState<SourceCounts>(EMPTY_COUNTS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    listReferenceCorpora(projectId)
      .then((items) => {
        if (!mounted) return;
        setCorpora(items);
        setSelected(latestCorpus(items));
      })
      .catch((cause) => mounted && setError(cause instanceof Error ? cause.message : 'server_error'));
    return () => {
      mounted = false;
    };
  }, [projectId]);

  useEffect(() => {
    onReadyCorpusChange?.(selected?.status === 'ready' ? selected : null);
  }, [onReadyCorpusChange, selected]);

  const canStage = Boolean(selected && selected.status === 'staging' && !busy);
  const canBuild = Boolean(selected && selected.status === 'staging' && !busy);
  const summary = useMemo(
    () => [
      `INDD ${sourceCounts.plate_layout}`,
      `Links ${sourceCounts.plate_link}`,
      `AI ${sourceCounts.drawing_source}`,
    ].join(' · '),
    [sourceCounts],
  );

  async function createNewCorpus() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createReferenceCorpus(projectId);
      setCorpora((items) => [...items, created]);
      setSelected(created);
      setSourceCounts(EMPTY_COUNTS);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'server_error');
    } finally {
      setBusy(false);
    }
  }

  async function stageFiles(role: ReferenceCorpusSourceRole, event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (!selected || !files.length || !canStage) return;
    setBusy(true);
    setError(null);
    try {
      for (const file of files) {
        await uploadReferenceCorpusSource(projectId, selected.id, role, file);
        setSourceCounts((counts) => ({ ...counts, [role]: counts[role] + 1 }));
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'server_error');
    } finally {
      setBusy(false);
      event.target.value = '';
    }
  }

  async function buildGraph() {
    if (!selected || !canBuild) return;
    setBusy(true);
    setError(null);
    try {
      const built = await buildReferenceCorpus(projectId, selected.id);
      setSelected(built);
      setCorpora((items) => items.map((item) => (item.id === built.id ? built : item)));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'server_error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="reference-corpus-panel" aria-labelledby="reference-corpus-title">
      <div className="reference-corpus-header">
        <div>
          <p className="section-label">REFERENCE DATA</p>
          <h3 id="reference-corpus-title">기준 자료 구축</h3>
          <p className="reference-corpus-help">도판은 INDD + Links, 도면은 AI에서 구조를 추출해 Neo4j 기준 그래프로 만듭니다.</p>
        </div>
        <div className="reference-corpus-actions">
          <span className={`reference-corpus-status status-${selected?.status ?? 'none'}`}>
            {statusLabel(selected?.status)}
          </span>
          <button type="button" onClick={() => void createNewCorpus()} disabled={busy}>
            새 기준자료 구축
          </button>
        </div>
      </div>

      {selected && (
        <div className="reference-corpus-meta">
          <strong>Reference Corpus V{selected.revision}</strong>
          <span>{summary}</span>
          {selected.failureCode && <span className="reference-corpus-error">실패: {selected.failureCode}</span>}
        </div>
      )}

      <div className="reference-source-grid">
        <label className="reference-source-card">
          <span className="reference-source-title">도판 INDD</span>
          <span className="reference-source-description">InDesign 내부 도판번호와 실제 배치 Link를 authority로 사용</span>
          <input
            aria-label="도판 INDD 파일"
            type="file"
            accept=".indd"
            disabled={!canStage}
            onChange={(event) => void stageFiles('plate_layout', event)}
          />
        </label>

        <label className="reference-source-card">
          <span className="reference-source-title">Links 사진</span>
          <span className="reference-source-description">INDD가 실제로 배치한 원본 사진 provenance</span>
          <input
            aria-label="Links 사진 파일"
            type="file"
            accept=".jpg,.jpeg,.png,.tif,.tiff,image/jpeg,image/png,image/tiff"
            multiple
            disabled={!canStage}
            onChange={(event) => void stageFiles('plate_link', event)}
          />
        </label>

        <label className="reference-source-card">
          <span className="reference-source-title">도면 AI</span>
          <span className="reference-source-description">Illustrator 내부 artboard/text identifier를 authority로 사용</span>
          <input
            aria-label="도면 AI 파일"
            type="file"
            accept=".ai"
            multiple
            disabled={!canStage}
            onChange={(event) => void stageFiles('drawing_source', event)}
          />
        </label>
      </div>

      <div className="reference-corpus-footer">
        <p>파일명 숫자는 도판·도면 identity로 사용하지 않습니다.</p>
        <button type="button" onClick={() => void buildGraph()} disabled={!canBuild}>
          {busy ? '처리 중…' : '기준 그래프 구축'}
        </button>
      </div>

      {error && <p className="reference-corpus-error" role="alert">{error}</p>}
    </section>
  );
}
