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
  plate_pdf: 0,
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
  if (suffix === '.pdf') return 'plate_pdf';
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
      `PDF ${sourceCounts.plate_pdf}`,
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
          <p className="reference-corpus-help">Adobe 없이 도판 PDF를 publication authority로 사용하고, AI와 Links 원본을 evidence graph로 연결합니다. INDD는 선택적 provenance 자료로 보존할 수 있습니다.</p>
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
          <span className="reference-source-description">도판 PDF, 선택적 INDD, Links 사진을 함께 선택하면 상대경로를 그대로 보존합니다.</span>
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
          <span className="reference-source-title">도판 PDF</span>
          <span className="reference-source-description">Adobe-free 기준 도판 identity와 panel geometry의 authority</span>
          <input
            aria-label="도판 PDF 파일"
            type="file"
            accept=".pdf,application/pdf"
            multiple
            disabled={!canStage}
            onChange={(event) => void stageFiles('plate_pdf', event)}
          />
        </label>

        <label className="reference-source-card">
          <span className="reference-source-title">도판 INDD</span>
          <span className="reference-source-description">선택적 provenance 자료. Adobe-free build에는 필수가 아닙니다.</span>
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
          <span className="reference-source-description">도판 panel과 실제 원본 사진을 verified evidence로 연결할 후보 원본</span>
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
          <span className="reference-source-description">PDF-compatible AI text/content와 본문 context를 evidence graph로 교차 검증합니다.</span>
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
        <p>파일명만으로 canonical identity를 확정하지 않습니다. direct 또는 독립 evidence가 검증된 derived identity만 기준 그래프로 승격합니다.</p>
        <button type="button" onClick={() => void buildGraph()} disabled={!canBuild}>
          {busy ? '처리 중…' : '기준 그래프 구축'}
        </button>
      </div>

      {error && <p className="reference-corpus-error" role="alert">{error}</p>}
    </section>
  );
}
