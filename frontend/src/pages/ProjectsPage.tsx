import { FormEvent, useEffect, useState } from 'react';

import { ApiError, createProject, fetchProjects, type Project } from '../api';

type Props = {
  onCreated: (project: Project) => void;
  onSelect?: (project: Project) => void;
};

export function ProjectsPage({ onCreated, onSelect }: Props) {
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [errorCode, setErrorCode] = useState<string | null>(null);

  const [projects, setProjects] = useState<Project[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const handleSelect = onSelect ?? onCreated;

  async function loadProjectList() {
    setLoadingProjects(true);
    setLoadError(null);
    try {
      const list = await fetchProjects();
      setProjects(list);
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.code : 'server_error');
    } finally {
      setLoadingProjects(false);
    }
  }

  useEffect(() => {
    loadProjectList();
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || submitting) return;

    setSubmitting(true);
    setErrorCode(null);
    try {
      const created = await createProject(name.trim());
      onCreated(created);
    } catch (error) {
      setErrorCode(error instanceof ApiError ? error.code : 'server_error');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ display: 'grid', gap: '24px' }}>
      {/* 1. 기존 프로젝트 목록 */}
      <section className="panel" aria-labelledby="existing-title">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <p className="section-label">등록된 프로젝트</p>
            <h2 id="existing-title">진행 중인 검수 프로젝트</h2>
            <p className="muted">이전에 생성된 프로젝트를 선택하여 이어서 검수를 진행합니다.</p>
          </div>
          <button
            type="button"
            className="secondary-button"
            onClick={loadProjectList}
            disabled={loadingProjects}
            style={{ fontSize: '0.85rem', padding: '6px 12px' }}
          >
            {loadingProjects ? '새로고침 중…' : '목록 새로고침'}
          </button>
        </div>

        {loadingProjects ? (
          <p className="muted">프로젝트 목록을 불러오는 중입니다…</p>
        ) : loadError ? (
          <p className="error-code">목록 조회 오류: {loadError}</p>
        ) : projects.length === 0 ? (
          <div className="empty-state" style={{ padding: '16px 0' }}>
            <p>등록된 프로젝트가 없습니다. 아래에서 새 프로젝트를 생성해 주세요.</p>
          </div>
        ) : (
          <div style={{ display: 'grid', gap: '10px' }}>
            {projects.map((p) => (
              <div
                key={p.id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '14px 18px',
                  background: '#ffffff',
                  border: '1px solid rgb(50 65 55 / 12%)',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  transition: 'border-color 0.15s ease',
                }}
                onClick={() => handleSelect(p)}
              >
                <div>
                  <h3 style={{ margin: '0 0 4px', fontSize: '1.05rem', color: '#183328', fontWeight: 600 }}>
                    {p.name}
                  </h3>
                  <p style={{ margin: 0, fontSize: '0.78rem', color: '#88928a', fontFamily: 'monospace' }}>
                    ID: {p.id}
                    {p.internalCode ? ` · 코드: ${p.internalCode}` : ''}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleSelect(p);
                  }}
                  style={{ whiteSpace: 'nowrap' }}
                >
                  프로젝트 열기 →
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 2. 새 프로젝트 생성 */}
      <section className="panel" aria-labelledby="create-title">
        <div>
          <p className="section-label">새 검수 작업</p>
          <h2 id="create-title">새 프로젝트 만들기</h2>
          <p className="muted">새로운 고고학 보고서 검수 프로젝트를 생성합니다.</p>
        </div>

        <form onSubmit={submit} className="form-stack">
          <label htmlFor="project-name">프로젝트명</label>
          <input
            id="project-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={200}
            autoComplete="off"
            placeholder="예: 논산 산노리 산17-1번지 유적 발굴조사보고서"
            required
          />
          <button type="submit" disabled={submitting || !name.trim()}>
            {submitting ? '생성 중…' : '프로젝트 생성'}
          </button>
        </form>

        {errorCode && <p className="error-code">{errorCode}</p>}
      </section>
    </div>
  );
}
