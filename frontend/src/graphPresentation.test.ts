import { describe, expect, it } from 'vitest';

import { relationshipLabel, semanticNodeTitle } from './graphPresentation';

describe('semanticNodeTitle', () => {
  it('uses archaeological labels instead of technical ids', () => {
    expect(
      semanticNodeTitle('ArchaeologyObject', {
        id: 'obj-uuid',
        point: '1지점',
        number: '6호',
        type: '석관묘',
        period: '청동기시대',
      }),
    ).toBe('[유구] 1지점 6호 석관묘 (청동기시대)');

    expect(
      semanticNodeTitle('Plate', {
        id: 'plate-uuid',
        number: '45',
        title: '1지점 청동기시대 6호 석관묘',
      }),
    ).toBe('[도판 45] 1지점 청동기시대 6호 석관묘');

    expect(
      semanticNodeTitle('PlatePanel', {
        id: 'panel-uuid',
        plate_number: '45',
        panel_index: 3,
        caption: "토층 A-A'",
      }),
    ).toBe("[도판 45 · 패널 3] 토층 A-A'");

    expect(
      semanticNodeTitle('Drawing', { number: '30', title: '1지점 6호 석관묘 평·단면도' }),
    ).toBe('[도면 30] 1지점 6호 석관묘 평·단면도');

    expect(semanticNodeTitle('Reference', { ref_type: 'plate', number: '45' })).toBe(
      '[본문 인용] 도판 45',
    );
  });

  it('never falls back to a uuid prefix when semantic metadata is missing', () => {
    expect(
      semanticNodeTitle('Plate', { id: '550e8400-e29b-41d4-a716-446655440000' }),
    ).toBe('[도판] 식별 정보 없음');
    expect(
      semanticNodeTitle('CorrectionCandidate', { id: 'candidate-very-technical-id' }),
    ).toBe('[교열 제안] 검수 후보');
  });

  it('may show an OriginalAsset filename only as provenance display metadata', () => {
    expect(
      semanticNodeTitle('OriginalAsset', {
        originalName: '4. 조사 후_45.JPG',
        assetKind: 'linked_photo',
        provenanceStatus: 'unlinked',
      }),
    ).toBe('[원천 사진] 4. 조사 후_45.JPG · canonical 미연결');
  });
});

describe('relationshipLabel', () => {
  it.each([
    ['RESOLVES_TO', '인용 대상 연결'],
    ['MENTIONS', '유구 언급'],
    ['DEPICTS', '유구 실물 묘사'],
    ['ABOUT', '대상 유구'],
    ['SUPPORTED_BY', '근거'],
    ['EXTRACTED_FROM', '추출 위치'],
    ['FROM_VERSION', '문서 버전'],
    ['HAS_PANEL', '세부 사진 포함'],
    ['HAS_REGION', '도면 영역 포함'],
    ['PRECEDES', '이전 검수 버전'],
    ['DERIVED_FROM', '원천 자료'],
  ])('%s -> %s', (edge, label) => {
    expect(relationshipLabel(edge)).toBe(label);
  });

  it('keeps unknown edge names available as technical fallback', () => {
    expect(relationshipLabel('CUSTOM_EDGE')).toBe('CUSTOM_EDGE');
  });
});
