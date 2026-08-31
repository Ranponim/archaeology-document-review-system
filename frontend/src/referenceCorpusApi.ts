export type ReferenceCorpusStatus =
  | 'staging'
  | 'converting'
  | 'validating'
  | 'canonicalizing'
  | 'graph_validating'
  | 'ready'
  | 'failed';

export type ReferenceCorpus = {
  id: string;
  projectId: string;
  revision: number;
  status: ReferenceCorpusStatus;
  sourceSetHash?: string;
  converterVersion?: string;
  manifestSchemaVersion?: string;
  canonicalizerVersion?: string;
  buildIdentity?: string;
  createdAt?: string | null;
  readyAt?: string | null;
  failureCode?: string | null;
};

export type ReferenceCorpusSourceRole = 'plate_layout' | 'plate_pdf' | 'plate_link' | 'drawing_source';

export type ReferenceCorpusSource = {
  id: string;
  role: ReferenceCorpusSourceRole;
  originalName: string;
  relativePath: string;
  sha256: string;
};

async function readJson<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = typeof payload?.code === 'string' ? payload.code : `http_${response.status}`;
    throw new Error(code);
  }
  return payload as T;
}

export async function listReferenceCorpora(projectId: string): Promise<ReferenceCorpus[]> {
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/reference-corpora`);
  return readJson<ReferenceCorpus[]>(response);
}

export async function createReferenceCorpus(projectId: string): Promise<ReferenceCorpus> {
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/reference-corpora`, {
    method: 'POST',
  });
  return readJson<ReferenceCorpus>(response);
}

export async function uploadReferenceCorpusSource(
  projectId: string,
  corpusId: string,
  role: ReferenceCorpusSourceRole,
  file: File,
  relativePath?: string,
): Promise<ReferenceCorpusSource> {
  const body = new FormData();
  body.append('file', file);
  const params = new URLSearchParams({ role });
  const path = (relativePath || file.webkitRelativePath || file.name).replaceAll('\\', '/');
  if (path) {
    params.set('relativePath', path);
  }
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/reference-corpora/${encodeURIComponent(corpusId)}/sources?${params.toString()}`,
    { method: 'POST', body },
  );
  return readJson<ReferenceCorpusSource>(response);
}

export async function buildReferenceCorpus(projectId: string, corpusId: string): Promise<ReferenceCorpus> {
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/reference-corpora/${encodeURIComponent(corpusId)}/build`,
    { method: 'POST' },
  );
  return readJson<ReferenceCorpus>(response);
}

export async function getReferenceCorpus(projectId: string, corpusId: string): Promise<ReferenceCorpus> {
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/reference-corpora/${encodeURIComponent(corpusId)}`,
  );
  return readJson<ReferenceCorpus>(response);
}
