import { useState } from 'react';

import type { Project } from './api';
import { ProjectDetailPage } from './pages/ProjectDetailPage';
import { ProjectsPage } from './pages/ProjectsPage';

export function App() {
  const [project, setProject] = useState<Project | null>(null);

  return (
    <main className="app-shell">
      <header className="hero">
        <p className="eyebrow">LOCAL REVIEW WORKSPACE</p>
        <h1>고고학 문서 검수</h1>
        <p>원본을 보존한 채 분석 작업을 등록하고 진행 상태를 확인합니다.</p>
      </header>

      {project ? (
        <ProjectDetailPage project={project} />
      ) : (
        <ProjectsPage onCreated={setProject} />
      )}
    </main>
  );
}
