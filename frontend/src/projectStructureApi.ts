export type ProjectStructureNodeType =
  | 'project'
  | 'material_group'
  | 'document'
  | 'document_version'
  | 'page_group'
  | 'page'
  | 'textblock_group'
  | 'text_block'
  | 'caption_group'
  | 'caption'
  | 'reference_group'
  | 'reference'
  | 'plate_group'
  | 'plate'
  | 'panel_group'
  | 'plate_panel'
  | 'drawing_group'
  | 'drawing'
  | 'region_group'
  | 'drawing_region'
  | 'source_asset_group'
  | 'source_kind_group'
  | 'original_asset'
  | 'review_round_group'
  | 'review_round'
  | 'version_reference'
  | 'archaeology_object_group'
  | 'archaeology_object';

export type ProjectStructureRelationshipTarget = {
  id: string;
  nodeType: ProjectStructureNodeType;
  label: string;
};

export type ProjectStructureRelationship = {
  type: string;
  direction: 'in' | 'out' | string;
  target: ProjectStructureRelationshipTarget;
};

export type ProjectStructureNode = {
  id: string;
  nodeType: ProjectStructureNodeType;
  label: string;
  subtitle?: string | null;
  sourceSystem: 'neo4j' | 'derived_group' | string;
  status?: string | null;
  expandable: boolean;
  childCount: number;
  badges: string[];
  details: Record<string, unknown>;
  relationships: ProjectStructureRelationship[];
};

export type ProjectStructureRoot = {
  projectId: string;
  root: ProjectStructureNode;
  groups: ProjectStructureNode[];
};

export type ProjectStructureChildren = {
  items: ProjectStructureNode[];
  offset: number;
  limit: number;
  total: number;
  hasMore: boolean;
};

async function decode<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`project_structure_${response.status}`);
  return response.json() as Promise<T>;
}

export async function fetchProjectStructure(projectId: string): Promise<ProjectStructureRoot> {
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/structure`);
  return decode<ProjectStructureRoot>(response);
}

export async function fetchProjectStructureChildren(
  projectId: string,
  nodeType: ProjectStructureNodeType,
  nodeId: string,
  offset = 0,
  limit = 50,
): Promise<ProjectStructureChildren> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/structure/nodes/${encodeURIComponent(nodeType)}/${encodeURIComponent(nodeId)}/children?${params.toString()}`,
  );
  return decode<ProjectStructureChildren>(response);
}

export async function fetchProjectStructureNode(
  projectId: string,
  nodeType: ProjectStructureNodeType,
  nodeId: string,
): Promise<ProjectStructureNode> {
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/structure/nodes/${encodeURIComponent(nodeType)}/${encodeURIComponent(nodeId)}`,
  );
  return decode<ProjectStructureNode>(response);
}
