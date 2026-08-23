import { ChangeEvent, type InputHTMLAttributes, useEffect, useMemo, useState } from 'react';

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

const DIRECTORY_INPUT_PROPS = {
  webkitdirectory: '',
} as unknown as InputHTMLAttributes<HTMLInputElement>;

const LINK_SUFFIXES = new Set(['.jpg', '.jpeg', '.png', '.tif', '.tiff']);

function latestCorpus(items: ReferenceCorpus[]): ReferenceCorpus | null {
  if (!items.length) return null;
  return [...items].sort((a, b) => b.revision - a.revision)[0];
}

function statusLabel(status: ReferenceCorpus['status'] | undefined): string {
  return status ? status.toUpperCase() : '없음';
}

function suffixOf(file: File): string {
  const index = file.name.lastIndexOf('.');
  return index >= 0 ? file.name.slice(index).toLowerCase() : '';
}

function packageRole(file: File): ReferenceCorpusSourceRole | null {
  const suffix = suffixOf(file);
  if (suffix === '.indd') return 'plate_layout';
  if (LINK_SUFFIXES.has(suffix)) return 'plate_link';
  return null;
}

function relativePathOf(file: File): string {
  return (file.webkitRelativePath || file.name).replaceAll('\\', '/');
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

  async function uploadFiles(files: File[], roleForFile: (file: File) => ReferenceCorpusSourceRole | null) {
    if (!selected || !files.length) return;
    for (const file of files) {
      const role = roleForFile(file);
      if (!role) continue;
      await uploadReferenceCorpusSource(
        projectId,
        selected.id,
        role,
        file,
        relativePathOf(file),
      );
      setSourceCounts((counts) => ({ ...counts, [role]: counts[role] + 1 }));
    }
  }

  async function stageFiles(role: ReferenceCorpusSourceRole, event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (!selected || !files.length || !canStage) return;
    setBusy(true);
    setError(null);
    try {
      await uploadFiles(files, () => role);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'server_error');
    } finally {
      setBusy(false);
      event.target.value = '';
    }
  }

  async function stagePackage(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (!selected || !files.length || !canStage) return;
    setBusy(true);
    setError(null);
    try {
      await uploadFiles(files, packageRole);
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
          <p className="reference-corpus-help">도판은 INDD + Links의 원래 폴더 구조를 보존하고, 도면은 AI에서 구조를 추출해 Neo4j 기준 그래프로 만듭니다.</p>
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
          <span className="reference-source-title">도판 패키지 폴더</span>
          <span className="reference-source-description">권장: INDD와 Links가 함께 있는 상위 폴더를 선택해 상대경로를 그대로 보존</span>
          <input
            {...DIRECTORY_INPUT_PROPS}
            aria-label="도판 패키지 폴더"
            type="file"
            multiple
            disabled={!canStage}
            onChange={(event) => void stagePackage(event)}
          />
        </label>

        <label className="reference-source-card">
          <span className="reference-source-title">도판 INDD</span>
          <span className="reference-source-description">호환용 단일 업로드. 완전 E2E에서는 위 패키지 폴더 사용 권장</span>
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
          <span className="reference-source-description">호환용 개별 업로드. 폴더 경로가 필요하면 패키지 폴더 사용</span>
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
        <p>파일명 숫자는 도판·도면 identity로 사용하지 않습니다. 패키지 폴더의 상대경로는 Link 재해석과 build identity에 포함됩니다.</p>
        <button type="button" onClick={() => void buildGraph()} disabled={!canBuild}>
          {busy ? '처리 중…' : '기준 그래프 구축'}
        </button>
      </div>

      {error && <p className="reference-corpus-error" role="alert">{error}</p>}
    </section>
  );
}
