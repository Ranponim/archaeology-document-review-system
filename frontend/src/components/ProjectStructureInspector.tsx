import { isTechnicalDetailKey, relationshipLabel } from '../graphPresentation';
import type {
  ProjectStructureNode,
  ProjectStructureRelationshipTarget,
} from '../projectStructureApi';
import { ProjectStructureStatusBadge } from './ProjectStructureStatusBadge';

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}

type Props = {
  node: ProjectStructureNode | null;
  loading?: boolean;
  onJump: (target: ProjectStructureRelationshipTarget) => void;
};

export function ProjectStructureInspector({ node, loading, onJump }: Props) {
  if (loading) return <aside className="structure-inspector"><p>상세 정보를 불러오는 중…</p></aside>;
  if (!node) {
    return (
      <aside className="structure-inspector">
        <p className="section-label">SELECTED NODE</p>
        <h3>항목을 선택하세요</h3>
        <p className="muted">왼쪽 트리에서 파일, 페이지, 도판, 도면 또는 검수 세트를 클릭하면 실제 저장·그래프 상태를 보여줍니다.</p>
      </aside>
    );
  }

  const allDetails = Object.entries(node.details ?? {}).filter(([, value]) => value !== null && value !== undefined && value !== '');
  const normalDetails = allDetails.filter(([key]) => !isTechnicalDetailKey(key));
  const technicalDetails = allDetails.filter(([key]) => isTechnicalDetailKey(key));

  return (
    <aside className="structure-inspector" aria-label="프로젝트 구조 상세">
      <div className="structure-inspector-heading">
        <div>
          <p className="section-label">SELECTED NODE</p>
          <h3>{node.label}</h3>
          {node.subtitle ? <p className="muted">{node.subtitle}</p> : null}
        </div>
        <span className="structure-source-system">{node.sourceSystem === 'neo4j' ? 'Neo4j' : 'UI 그룹'}</span>
      </div>

      <div className="structure-inspector-badges">
        {node.status ? <ProjectStructureStatusBadge text={node.status} /> : null}
        {node.badges.map((badge) => <ProjectStructureStatusBadge key={badge} text={badge} />)}
      </div>

      <section className="structure-facts" aria-labelledby="structure-facts-title">
        <h4 id="structure-facts-title">저장 / 그래프 정보</h4>
        <dl>
          {normalDetails.map(([key, value]) => (
            <div key={key}><dt>{key}</dt><dd className={typeof value === 'object' ? 'structure-json-value' : ''}>{formatValue(value)}</dd></div>
          ))}
        </dl>
      </section>

      <section className="structure-relationships" aria-labelledby="structure-relationships-title">
        <h4 id="structure-relationships-title">Neo4j 연결 관계</h4>
        {node.relationships.length === 0 ? <p className="muted">표시할 교차 관계가 없습니다.</p> : (
          <div className="structure-relationship-list">
            {node.relationships.map((relationship, index) => (
              <div className="structure-relationship" key={`${relationship.type}-${relationship.target.id}-${index}`}>
                <span className="structure-relation-direction">{relationship.direction === 'in' ? '←' : '→'}</span>
                <strong title={relationship.type}>{relationshipLabel(relationship.type)}</strong>
                <button type="button" onClick={() => onJump(relationship.target)}>{relationship.target.label}</button>
              </div>
            ))}
          </div>
        )}
      </section>

      <details className="structure-technical-details">
        <summary>기술 정보</summary>
        <dl>
          <div><dt>ID</dt><dd><code>{node.id}</code></dd></div>
          <div><dt>Node Type</dt><dd>{node.nodeType}</dd></div>
          {technicalDetails.map(([key, value]) => (
            <div key={key}><dt>{key}</dt><dd>{formatValue(value)}</dd></div>
          ))}
        </dl>
      </details>

      <p className="structure-readonly-note">읽기 전용 화면입니다. 이 화면에서는 파일이나 그래프 관계를 변경하지 않습니다.</p>
    </aside>
  );
}
