import type { ProjectStructureNode } from '../projectStructureApi';
import { ProjectStructureStatusBadge } from './ProjectStructureStatusBadge';

export type StructureChildrenState = {
  items: ProjectStructureNode[];
  total: number;
  loading?: boolean;
};

type Props = {
  node: ProjectStructureNode;
  depth?: number;
  expanded: Set<string>;
  childrenByKey: Record<string, StructureChildrenState>;
  selectedKey?: string | null;
  onToggle: (node: ProjectStructureNode) => void;
  onSelect: (node: ProjectStructureNode) => void;
  onMore: (node: ProjectStructureNode) => void;
};

export function structureNodeKey(node: Pick<ProjectStructureNode, 'nodeType' | 'id'>): string {
  return `${node.nodeType}:${node.id}`;
}

export function ProjectStructureTree({
  node,
  depth = 0,
  expanded,
  childrenByKey,
  selectedKey,
  onToggle,
  onSelect,
  onMore,
}: Props) {
  const key = structureNodeKey(node);
  const isExpanded = expanded.has(key);
  const children = childrenByKey[key];
  const loadedCount = children?.items.length ?? 0;
  const hasMore = Boolean(children && loadedCount < children.total);
  const isSelected = selectedKey === key;

  function activate() {
    onSelect(node);
    if (node.expandable) onToggle(node);
  }

  return (
    <div className="structure-tree-branch">
      <button
        type="button"
        className={`structure-tree-row ${isSelected ? 'selected' : ''}`}
        style={{ paddingLeft: `${12 + depth * 22}px` }}
        onClick={activate}
        aria-expanded={node.expandable ? isExpanded : undefined}
      >
        <span className="structure-tree-caret" aria-hidden="true">
          {node.expandable ? (isExpanded ? '▾' : '▸') : '•'}
        </span>
        <span className="structure-tree-main">
          <span className="structure-tree-label">{node.label}</span>
          {node.subtitle ? <span className="structure-tree-subtitle">{node.subtitle}</span> : null}
        </span>
        <span className="structure-tree-badges">
          {node.badges.slice(0, 4).map((badge) => (
            <ProjectStructureStatusBadge key={badge} text={badge} />
          ))}
          {node.childCount > 0 && node.badges.length === 0 ? (
            <span className="structure-count">{node.childCount}</span>
          ) : null}
        </span>
      </button>

      {isExpanded ? (
        <div className="structure-tree-children">
          {children?.loading && loadedCount === 0 ? (
            <div className="structure-tree-loading" style={{ paddingLeft: `${36 + depth * 22}px` }}>
              불러오는 중…
            </div>
          ) : null}
          {children?.items.map((child) => (
            <ProjectStructureTree
              key={structureNodeKey(child)}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              childrenByKey={childrenByKey}
              selectedKey={selectedKey}
              onToggle={onToggle}
              onSelect={onSelect}
              onMore={onMore}
            />
          ))}
          {hasMore ? (
            <button
              type="button"
              className="structure-more-button"
              style={{ marginLeft: `${36 + depth * 22}px` }}
              onClick={() => onMore(node)}
              disabled={children?.loading}
            >
              {children?.loading ? '불러오는 중…' : `더 보기 (${loadedCount}/${children?.total})`}
            </button>
          ) : null}
          {children && !children.loading && children.total === 0 ? (
            <div className="structure-tree-empty" style={{ paddingLeft: `${36 + depth * 22}px` }}>
              하위 항목 없음
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
