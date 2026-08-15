import { FormEvent, useState } from 'react';

import { ApiError, createProject, type Project } from '../api';

type Props = {
  onCreated: (project: Project) => void;
};

export function ProjectsPage({ onCreated }: Props) {
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [errorCode, setErrorCode] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || submitting) return;

    setSubmitting(true);
    setErrorCode(null);
    try {
      onCreated(await createProject(name.trim()));
    } catch (error) {
      setErrorCode(error instanceof ApiError ? error.code : 'server_error');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="create-title">
      <div>
        <p className="section-label">새 검수 작업</p>
        <h2 id="create-title">프로젝트 만들기</h2>
        <p className="muted">프로젝트 생성 후 원본 PDF를 등록할 수 있습니다.</p>
      </div>

      <form onSubmit={submit} className="form-stack">
        <label htmlFor="project-name">프로젝트명</label>
        <input
          id="project-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={200}
          autoComplete="off"
          required
        />
        <button type="submit" disabled={submitting || !name.trim()}>
          {submitting ? '생성 중…' : '프로젝트 생성'}
        </button>
      </form>

      {errorCode && <p className="error-code">{errorCode}</p>}
    </section>
  );
}
