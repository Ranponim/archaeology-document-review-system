import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  fetchProjectStructure,
  fetchProjectStructureChildren,
  fetchProjectStructureNode,
  type ProjectStructureNode,
  type ProjectStructureNodeType,
  type ProjectStructureRelationshipTarget,
  type ProjectStructureRoot,
} from '../projectStructureApi';
import { ProjectStructureInspector } from './ProjectStructureInspector';
import {
  ProjectStructureTree,
  structureNodeKey,
  type StructureChildrenState,
} from './ProjectStructureTree';
import '../project-structure.css';

type InitialSelection = {
  nodeType: ProjectStructureNodeType;
  id: string;
};

type Props = {
  projectId: string;
  initialSelection?: InitialSelection;
};

const PAGE_SIZE = 50;

export function ProjectStructureExplorer({ projectId, initialSelection }: Props) {
  const [root, setRoot] = useState<ProjectStructureRoot | null>(null);
  const [rootLoading, setRootLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [childrenByKey, setChildrenByKey] = useState<Record<string, StructureChildrenState>>({});
  const [selected, setSelected] = useState<ProjectStructureNode | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const loadRoot = useCallback(async () => {
    try {
      const next = await fetchProjectStructure(projectId);
      setRoot(next);
      setError(null);
    } catch {
      setError('프로젝트 구조를 불러오지 못했습니다.');
    } finally {
      setRootLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    setRootLoading(true);
    setExpanded(new Set());
    setChildrenByKey({});
    setSelected(null);
    setSelectedKey(null);
    void loadRoot();
  }, [loadRoot]);

  useEffect(() => {
    const timer = window.setInterval(() => void loadRoot(), 5000);
    return () => window.clearInterval(timer);
  }, [loadRoot]);

  const loadDetail = useCallback(async (
    nodeType: ProjectStructureNodeType,
    id: string,
  ) => {
    setDetailLoading(true);
    try {
      const detail = await fetchProjectStructureNode(projectId, nodeType, id);
      setSelected(detail);
      setSelectedKey(structureNodeKey(detail));
      setError(null);
    } catch {
      setError('선택한 항목의 상세 정보를 불러오지 못했습니다.');
    } finally {
      setDetailLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (!initialSelection) return;
    void loadDetail(initialSelection.nodeType, initialSelection.id);
  }, [initialSelection?.id, initialSelection?.nodeType, loadDetail]);

  const fetchChildren = useCallback(async (node: ProjectStructureNode, append: boolean) => {
    const key = structureNodeKey(node);
    const current = childrenByKey[key];
    const offset = append ? current?.items.length ?? 0 : 0;
    setChildrenByKey((prev) => ({
      ...prev,
      [key]: {
        items: append ? prev[key]?.items ?? [] : [],
        total: prev[key]?.total ?? node.childCount,
        loading: true,
      },
    }));
    try {
      const response = await fetchProjectStructureChildren(
        projectId,
        node.nodeType,
        node.id,
        offset,
        PAGE_SIZE,
      );
      setChildrenByKey((prev) => ({
        ...prev,
        [key]: {
          items: append ? [...(prev[key]?.items ?? []), ...response.items] : response.items,
          total: response.total,
          loading: false,
        },
      }));
    } catch {
      setChildrenByKey((prev) => ({
        ...prev,
        [key]: { ...(prev[key] ?? { items: [], total: 0 }), loading: false },
      }));
      setError('하위 구조를 불러오지 못했습니다.');
    }
  }, [childrenByKey, projectId]);

  const handleToggle = useCallback((node: ProjectStructureNode) => {
    const key = structureNodeKey(node);
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
        if (!childrenByKey[key]) void fetchChildren(node, false);
      }
      return next;
    });
  }, [childrenByKey, fetchChildren]);

  const handleSelect = useCallback((node: ProjectStructureNode) => {
    const key = structureNodeKey(node);
    setSelectedKey(key);
    if (node.sourceSystem === 'derived_group') {
      setSelected(node);
      return;
    }
    void loadDetail(node.nodeType, node.id);
  }, [loadDetail]);

  const handleJump = useCallback((target: ProjectStructureRelationshipTarget) => {
    void loadDetail(target.nodeType, target.id);
  }, [loadDetail]);

  const groups = useMemo(() => root?.groups ?? [], [root]);

  if (rootLoading && !root) {
    return <section className="panel project-structure-explorer"><p>프로젝트 구조를 불러오는 중…</p></section>;
  }

  return (
    <section className="panel project-structure-explorer" aria-labelledby="project-structure-title">
      <div className="structure-header">
        <div>
          <p className="section-label">PROJECT STRUCTURE</p>
          <h2 id="project-structure-title">프로젝트 자료 · 그래프 구조</h2>
          <p className="muted">파일 저장, Neo4j 적재, 파싱 결과를 읽기 전용 트리로 확인합니다. 필요한 항목만 클릭해서 펼칩니다.</p>
        </div>
        <button type="button" className="structure-refresh" onClick={() => void loadRoot()}>
          새로고침
        </button>
      </div>

      {error ? <p className="error-code" role="alert">{error}</p> : null}

      <div className="project-structure-layout">
        <div className="structure-tree-pane" aria-label="프로젝트 구조 트리">
          {root ? (
            <button
              type="button"
              className={`structure-project-root ${selectedKey === structureNodeKey(root.root) ? 'selected' : ''}`}
              onClick={() => handleSelect(root.root)}
            >
              <span>▣</span>
              <span><strong>{root.root.label}</strong><small>{root.root.subtitle}</small></span>
            </button>
          ) : null}
          {groups.map((group) => (
            <ProjectStructureTree
              key={structureNodeKey(group)}
              node={group}
              expanded={expanded}
              childrenByKey={childrenByKey}
              selectedKey={selectedKey}
              onToggle={handleToggle}
              onSelect={handleSelect}
              onMore={(node) => void fetchChildren(node, true)}
            />
          ))}
        </div>
        <ProjectStructureInspector node={selected} loading={detailLoading} onJump={handleJump} />
      </div>
    </section>
  );
}
