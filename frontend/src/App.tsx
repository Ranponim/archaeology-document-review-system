import { useEffect, useState } from 'react';

import { fetchProject, type Project } from './api';
import { ProjectStructureExplorer } from './components/ProjectStructureExplorer';
import { ProjectDetailPage } from './pages/ProjectDetailPage';
import { ProjectsPage } from './pages/ProjectsPage';

const STORAGE_KEY = 'archaeology_selected_project_id';
type ProjectMode = 'structure' | 'review';

export function App() {
  const [project, setProject] = useState<Project | null>(null);
  const [loadingInitial, setLoadingInitial] = useState(true);
  const [projectMode, setProjectMode] = useState<ProjectMode>('structure');

  useEffect(() => {
    async function restoreProject() {
      const urlParams = new URLSearchParams(window.location.search);
      const savedId = urlParams.get('projectId') || localStorage.getItem(STORAGE_KEY);

      if (savedId) {
        try {
          const detail = await fetchProject(savedId);
          setProject({
            id: detail.id,
            name: detail.name,
            internalCode: detail.internalCode,
          });
          setProjectMode('structure');
          localStorage.setItem(STORAGE_KEY, detail.id);
        } catch {
          localStorage.removeItem(STORAGE_KEY);
          window.history.replaceState({}, '', window.location.pathname);
        }
      }
      setLoadingInitial(false);
    }

    restoreProject();
  }, []);

  function handleSelectProject(selected: Project) {
    setProject(selected);
    setProjectMode('structure');
    localStorage.setItem(STORAGE_KEY, selected.id);
    const url = new URL(window.location.href);
    url.searchParams.set('projectId', selected.id);
    window.history.pushState({}, '', url.toString());
  }

  function handleBack() {
    setProject(null);
    setProjectMode('structure');
    localStorage.removeItem(STORAGE_KEY);
    const url = new URL(window.location.href);
    url.searchParams.delete('projectId');
    window.history.pushState({}, '', url.toString());
  }

  return (
    <main className="app-shell">
      <header className="hero">
        <p className="eyebrow">LOCAL REVIEW WORKSPACE</p>
        <h1>고고학 문서 검수</h1>
        <p>원본을 보존한 채 분석 작업을 등록하고 진행 상태를 확인합니다.</p>
      </header>

      {loadingInitial ? (
        <p className="muted">프로젝트를 불러오는 중입니다…</p>
      ) : project ? (
        <>
          <nav className="project-mode-switcher" aria-label="프로젝트 작업 화면">
            <button
              type="button"
              className={`project-mode-tab ${projectMode === 'structure' ? 'active' : ''}`}
              aria-pressed={projectMode === 'structure'}
              onClick={() => setProjectMode('structure')}
            >
              프로젝트 구조
            </button>
            <button
              type="button"
              className={`project-mode-tab ${projectMode === 'review' ? 'active' : ''}`}
              aria-pressed={projectMode === 'review'}
              onClick={() => setProjectMode('review')}
            >
              검수 작업
            </button>
            <span className="project-mode-spacer" />
            {projectMode === 'structure' ? (
              <button type="button" className="project-mode-back" onClick={handleBack}>
                ← 프로젝트 목록
              </button>
            ) : null}
          </nav>
          {projectMode === 'structure' ? (
            <ProjectStructureExplorer projectId={project.id} />
          ) : (
            <ProjectDetailPage project={project} onBack={handleBack} />
          )}
        </>
      ) : (
        <ProjectsPage
          onCreated={handleSelectProject}
          onSelect={handleSelectProject}
        />
      )}
    </main>
  );
}
