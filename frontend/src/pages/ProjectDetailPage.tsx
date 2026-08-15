import { ChangeEvent, useEffect, useRef, useState } from 'react';

import {
  ApiError,
  getProject,
  type Project,
  type ProjectDetail,
  uploadDocument,
} from '../api';

type Props = {
  project: Project;
};

export function ProjectDetailPage({ project }: Props) {
  const [detail, setDetail] = useState<ProjectDetail>({
    ...project,
    documentVersions: [],
    analysisRuns: [],
  });
  const [uploading, setUploading] = useState(false);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const pollTimer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (pollTimer.current !== null) window.clearTimeout(pollTimer.current);
    },
    [],
  );

  async function refreshLater() {
    pollTimer.current = window.setTimeout(async () => {
      try {
        const next = await getProject(project.id);
        setDetail(next);
        if (next.analysisRuns.some((run) => ['queued', 'running'].includes(run.status))) {
          void refreshLater();
        }
      } catch {
        setErrorCode('server_error');
      }
    }, 2000);
  }

  async function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || uploading) return;

    setUploading(true);
    setErrorCode(null);
    try {
      const accepted = await uploadDocument(project.id, file);
      setDetail((current) => ({
        ...current,
        documentVersions: [
          ...current.documentVersions,
          {
            id: accepted.documentVersionId,
            documentId: accepted.documentVersionId,
            originalName: file.name,
            mimeType: file.type || 'application/octet-stream',
            sizeBytes: file.size,
            stage: 'source',
          },
        ],
        analysisRuns: [
          ...current.analysisRuns,
          {
            id: accepted.analysisRunId,
            status: 'queued',
            step: 'ingest',
            documentVersionId: accepted.documentVersionId,
            errorCode: null,
            retryable: false,
          },
        ],
      }));
      void refreshLater();
    } catch (error) {
      setErrorCode(error instanceof ApiError ? error.code : 'server_error');
    } finally {
      setUploading(false);
      event.target.value = '';
    }
  }

  return (
    <section className="workspace" aria-labelledby="project-title">
      <div className="panel project-summary">
        <div>
          <p className="section-label">현재 프로젝트</p>
          <h2 id="project-title">{project.name}</h2>
        </div>
        <label className={`file-button ${uploading ? 'disabled' : ''}`}>
          <span>{uploading ? '업로드 중…' : '원본 PDF 선택'}</span>
          <input
            type="file"
            accept="application/pdf,.pdf"
            aria-label="원본 파일"
            onChange={chooseFile}
            disabled={uploading}
          />
        </label>
      </div>

      {errorCode && <p className="error-code">{errorCode}</p>}

      <section className="panel" aria-labelledby="runs-title">
        <div>
          <p className="section-label">문서 버전별 작업 상태</p>
          <h2 id="runs-title">분석 현황</h2>
        </div>

        {detail.documentVersions.length === 0 ? (
          <p className="empty-state">등록된 원본이 없습니다.</p>
        ) : (
          <div className="run-list">
            {detail.documentVersions.map((version) => {
              const run = detail.analysisRuns.find(
                (candidate) => candidate.documentVersionId === version.id,
              );
              return (
                <article className="run-card" key={version.id}>
                  <div>
                    <strong>{version.originalName}</strong>
                    <span>{Math.max(1, Math.ceil(version.sizeBytes / 1024))} KB</span>
                  </div>
                  <div className="status-column">
                    <span className={`status status-${run?.status ?? 'unknown'}`}>
                      {run?.status ?? 'unknown'}
                    </span>
                    {run?.errorCode && <code>{run.errorCode}</code>}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </section>
  );
}
