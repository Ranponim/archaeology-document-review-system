const EDGE_LABELS: Record<string, string> = {
  RESOLVES_TO: '인용 대상 연결',
  MENTIONS: '유구 언급',
  DEPICTS: '유구 실물 묘사',
  ABOUT: '대상 유구',
  SUPPORTED_BY: '근거',
  EXTRACTED_FROM: '추출 위치',
  FROM_VERSION: '문서 버전',
  HAS_PANEL: '세부 사진 포함',
  HAS_REGION: '도면 영역 포함',
  PRECEDES: '이전 검수 버전',
  DERIVED_FROM: '원천 자료',
};

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : value === null || value === undefined ? '' : String(value).trim();
}

function compact(parts: string[]): string {
  return parts.filter(Boolean).join(' ').trim();
}

function sourceAssetStatus(props: Record<string, unknown>): string {
  const status = text(props.provenanceStatus ?? props.provenance_status);
  const labels: Record<string, string> = {
    unlinked: 'canonical 미연결',
    declared: '연결 선언',
    verified: '연결 검증',
    ambiguous: '연결 모호',
    missing_target: '대상 없음',
    conflict: '연결 충돌',
  };
  return labels[status] ?? (status || 'canonical 미연결');
}

export function semanticNodeTitle(
  label: string | undefined,
  props: Record<string, unknown>,
): string {
  switch (label) {
    case 'ArchaeologyObject': {
      const canonical = text(props.canonical_name ?? props.canonicalName);
      if (canonical) return `[유구] ${canonical}`;
      const base = compact([
        text(props.point),
        text(props.number),
        text(props.type),
      ]);
      const period = text(props.period);
      return base ? `[유구] ${base}${period ? ` (${period})` : ''}` : '[유구] 식별 정보 없음';
    }
    case 'Plate': {
      const number = text(props.number);
      const title = text(props.title);
      if (!number && !title) return '[도판] 식별 정보 없음';
      return compact([number ? `[도판 ${number}]` : '[도판]', title]);
    }
    case 'PlatePanel': {
      const plate = text(props.plate_number ?? props.plateNumber ?? props.number);
      const index = text(props.panel_index ?? props.panelIndex);
      const caption = text(props.caption ?? props.title);
      const tag = plate && index ? `[도판 ${plate} · 패널 ${index}]` : index ? `[도판 패널 ${index}]` : '[도판 패널]';
      return compact([tag, caption || (plate ? `도판 ${plate}` : '식별 정보 없음')]);
    }
    case 'Drawing': {
      const number = text(props.number);
      const title = text(props.title);
      if (!number && !title) return '[도면] 식별 정보 없음';
      return compact([number ? `[도면 ${number}]` : '[도면]', title]);
    }
    case 'DrawingRegion': {
      const number = text(props.number);
      const title = text(props.title);
      return compact([number ? `[도면 영역 ${number}]` : '[도면 영역]', title || '식별 정보 없음']);
    }
    case 'Reference': {
      const type = text(props.ref_type ?? props.refType);
      const number = text(props.number);
      const kind = type === 'drawing' ? '도면' : type === 'plate' ? '도판' : '참조';
      return number ? `[본문 인용] ${kind} ${number}` : '[본문 인용] 식별 정보 없음';
    }
    case 'TextBlock':
    case 'Caption': {
      const raw = text(props.text ?? props.raw_text ?? props.rawText ?? props.normalized_text);
      return raw ? `[본문 단락] “${raw.slice(0, 60)}${raw.length > 60 ? '…' : ''}”` : '[본문 단락] 내용 없음';
    }
    case 'CorrectionCandidate': {
      const category = text(props.rule_category ?? props.ruleCategory ?? props.category);
      return `[교열 제안] ${category || '검수 후보'}`;
    }
    case 'OriginalAsset': {
      const name = text(props.originalName ?? props.original_name) || '파일명 없음';
      const kind = text(props.assetKind ?? props.asset_kind);
      const prefix = kind === 'linked_photo' ? '[원천 사진]' : kind === 'drawing_source' ? '[원천 도면]' : kind === 'layout_source' ? '[조판 원본]' : kind === 'body_source' ? '[본문 원본]' : '[원천 자료]';
      return `${prefix} ${name} · ${sourceAssetStatus(props)}`;
    }
    default:
      return `[${label || '항목'}] 식별 정보 없음`;
  }
}

export function relationshipLabel(type: string): string {
  return EDGE_LABELS[type] ?? type;
}

export function isTechnicalDetailKey(key: string): boolean {
  return [
    'id', 'nodeType', 'node_type', 'neo4jLabel', 'sourceSha256', 'source_sha256',
    'sha256', 'storageUri', 'storage_uri', 'uri', 'documentVersionId', 'document_version_id',
  ].includes(key);
}
