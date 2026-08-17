# 후속 4대 과제 최종 설계 — Source Provenance & Archaeologist Usability

**Date:** 2026-08-18  
**Baseline:** `a6a54f282e22bdfc1d86b7e6f81a71f663d19269`  
**Branch:** `feature/source-provenance-remediation-20260818`  
**Status:** **FINAL / AUTHORITATIVE — implementation plan 전 사용자 확인 gate**

상세 코드 감사와 초안 문제점은 `docs/superpowers/reviews/2026-08-18-source-provenance-spec-review.md`에 기록한다. 이 문서와 초기 handoff/draft가 충돌하면 이 문서가 우선한다.

## 1. 목표

1. 프로젝트 카드·버튼은 hover 없이 항상 읽힌다.
2. Project에 `createdAt/updatedAt`을 완성하고 목록은 최신 생성순이다.
3. 그래프 UI는 UUID보다 고고학적 명칭과 한글 관계를 기본 표시한다.
4. HWP/HWPX, AI, INDD, JPG/PNG/TIFF 등 실제 `src/` 원천 자료는 canonical publication graph와 분리된 provenance 자료로 저장하고 Project Structure에서 읽기 전용으로 확인한다.

## 2. P0 identity invariant

filename은 canonical identity evidence가 아니다.

```text
4. 조사 후_45.JPG -> Plate 45          금지
22 (1).jpg        -> Plate 22/Panel 1  금지
도면30....ai      -> Drawing 30        금지
```

filename/relativePath는 저장·표시·manifest literal lookup에만 사용한다.

canonical `Plate/PlatePanel/Drawing/DrawingRegion`을 새로 만드는 authority는 기존 publication DocumentVersion ingest다.

```text
publication PDF
-> explicit publication identifier
-> canonical Plate / Drawing
```

AI/INDD/Links 사진/HWP는 canonical node를 새로 만들지 않는다.

Case 6의 authoritative path는 계속:

```text
TextBlock/Caption
-> Reference(type=plate, number=45)
-> RESOLVES_TO
-> canonical Plate/PlatePanel
```

이다. `_45.JPG`, `_91.JPG`는 missing target을 생성·복구하지 못한다.

OriginalAsset 사진은 supplementary provenance이며 이번 batch에서 canonical PDF render나 VLM canonical input을 대체하지 않는다. VLM acceptance는 계속 HOLD다.

## 3. Neo4j provenance model

기존 schema에 `OriginalAsset`이 이미 있으므로 persistent `SourceBundle`은 만들지 않는다.

```text
Project
├─ HAS_DOCUMENT -> Document -> HAS_VERSION -> DocumentVersion
│                                      ├─ HAS_PLATE -> Plate -> HAS_PANEL -> PlatePanel
│                                      └─ HAS_DRAWING -> Drawing -> HAS_REGION -> DrawingRegion
│
└─ HAS_ORIGINAL_ASSET -> OriginalAsset
```

새 provenance relation은 하나로 통일한다.

```text
DocumentVersion ─┐
PlatePanel       ├─[:DERIVED_FROM {method,status,manifestSha256,...}]-> OriginalAsset
Drawing          ┤
DrawingRegion    ┘
```

`PROVENANCED_BY`는 도입하지 않는다.

`DERIVED_FROM`은 explicit mapping이 있을 때만 생성한다. 기본 write는 `method=manifest_mapping`, `status=declared`. `filename_match` method는 존재할 수 없다.

모든 OriginalAsset read/write는 Project ownership path에서 시작하고 `OriginalAsset.projectId`도 같은 Project ID여야 한다.

## 4. OriginalAsset contract

필수 properties:

```text
id, projectId, uri, sha256, sizeBytes, mimeType,
originalName, relativePath, assetKind,
sourceRootName, importBatchId,
parseStatus, provenanceStatus, createdAt
```

`assetKind`:

```text
body_source | drawing_source | layout_source | linked_photo | other_source | provenance_manifest
```

`parseStatus`:

```text
stored | parsed | unsupported | failed
```

`provenanceStatus`:

```text
unlinked | declared | verified | ambiguous | missing_target | conflict
```

ID는 `project_id + normalized_relative_path + sha256` 기반 deterministic ID다. 동일 bytes/path 재import는 idempotent하고, 같은 path의 bytes가 바뀌면 기존 node를 덮지 않고 새 immutable OriginalAsset을 만든다.

## 5. Publication upload와 source import 분리

기존 `POST /api/projects/{project_id}/documents`는 reviewable publication input 전용이다. 이번 remediation에서 canonical document ingest는 PDF 기반을 유지한다. HWP/HWPX/AI/INDD/raw image가 이 endpoint를 통해 source-only DocumentVersion으로 들어가는 우회 경로는 fail closed 한다.

새 source path:

```text
SourceImportService
scripts/ingest_src_folder.py
```

흐름:

```text
source root
-> safe enumeration
-> FileStore immutable storage
-> OriginalAsset persistence
-> optional AI source inspection
-> optional manifest mapping
-> import report
```

public directory upload API/UI는 이번 범위 밖이다.

## 6. 형식별 규칙

### HWP/HWPX

OriginalAsset으로 저장한다. native HWP canonical parser는 이번에 새로 만들지 않는다.

### AI

항상 `OriginalAsset(assetKind=drawing_source)`로 저장한다. `AiSourceInspector`는 PDF-compatible stream이면 PyMuPDF로 text, page count, optional thumbnail, 내부 `도면 N` 같은 식별자를 **source metadata**로 기록할 수 있다.

하지만 AI는 `Drawing/Region` node를 생성하지 않는다. filename 숫자도 parse하지 않는다. canonical Drawing과 연결하려면 scoped manifest가 필요하다.

### INDD

`.indd`를 FileStore source storage에 추가하고 `layout_source`로 저장한다. native parse는 `unsupported`다.

### JPG/PNG/TIFF

Links 이미지는 `linked_photo`로 저장한다. filename 숫자는 identity에 사용하지 않는다.

## 7. Manifest contract

manifest는 UTF-8 JSON, SHA-256 감사값을 기록하고 자체도 `provenance_manifest` OriginalAsset으로 저장한다.

모든 target은 `documentVersionId` scope가 필수다.

```json
{
  "version": 1,
  "mappings": [{
    "asset": "도판(사진들)/Links/4. 조사 후_45.JPG",
    "target": {
      "documentVersionId": "plate-version-id",
      "nodeType": "PlatePanel",
      "nodeId": "panel-node-id"
    },
    "method": "manifest_mapping"
  }]
}
```

`nodeId` 대신 `documentVersionId + nodeType + publication identifier`도 허용하지만 해당 version 내부에서 정확히 1개 target이어야 한다.

검증:

1. target DocumentVersion이 같은 Project 소유인가?
2. target node가 그 version에서 실제 reachable한가?
3. identifier form이면 정확히 1개인가?
4. asset literal path가 source root 내부인가?
5. conflicting mapping이 없는가?

실패 시 edge를 만들지 않는다. basename 숫자 fallback은 없다.

manifest의 `declared` provenance는 expert truth가 아니다. source photo는 보조 표시만 하고 canonical PDF render/VLM input을 대체하지 않는다.

## 8. Filesystem safety

실제 `src` root 자체가 symlink일 수 있으므로 root symlink는 허용한다.

1. 입력 `sourceRoot`를 한 번 `resolve()`하고 trust boundary로 고정한다.
2. child/manifest asset의 resolved path가 boundary 내부인지 검증한다.
3. nested symlink가 밖으로 나가면 reject한다.
4. `..`, absolute asset path, drive escape는 reject한다.
5. 원본 source tree는 수정하지 않는다.

## 9. Project timestamps

Domain/API/frontend에 `createdAt/updatedAt`을 추가한다.

Project 생성 시 둘 다 기록하고 다음 mutation과 같은 Neo4j transaction에서 `updatedAt`을 갱신한다.

- Document/DocumentVersion 생성
- OriginalAsset 추가/provenance mapping
- ReviewRound 생성
- ReviewRound 승인

목록 권위 정렬:

```text
createdAt 존재 우선
-> createdAt DESC
-> name ASC
-> id ASC
-> legacy null createdAt 마지막
```

frontend는 다시 sort하지 않는다. null은 `생성일 기록 없음`으로 표시한다.

## 10. UI visibility

`.secondary-button`과 project card semantic CSS를 실제 정의한다. visibility-critical inline color/background를 제거한다.

base state에서 title/meta/refresh/open action과 keyboard focus가 보여야 하며 hover는 강조만 담당한다.

## 11. 고고학자 친화 graph UI

primary title에 UUID/SHA prefix/`id.slice()` fallback을 사용하지 않는다.

예:

```text
[유구] 1지점 6호 석관묘 (청동기시대)
[도판 45] 1지점 청동기시대 6호 석관묘
[도판 45 · 패널 3] 토층 A-A'
[도면 30] 1지점 6호 석관묘 평·단면도
[본문 인용] 도판 45
[원천 사진] 4. 조사 후_45.JPG · canonical 미연결
```

known relation:

```text
RESOLVES_TO -> 인용 대상 연결
MENTIONS -> 유구 언급
DEPICTS -> 유구 실물 묘사
ABOUT -> 대상 유구
SUPPORTED_BY -> 근거
EXTRACTED_FROM -> 추출 위치
FROM_VERSION -> 문서 버전
HAS_PANEL -> 세부 사진 포함
HAS_REGION -> 도면 영역 포함
PRECEDES -> 이전 검수 버전
DERIVED_FROM -> 원천 자료
```

frontend `graphPresentation.ts`는 EvidenceGraphExplorer/Inspector 표현을 담당하고 backend `ProjectStructureService`는 lazy tree semantic label을 담당한다. 둘 다 ID fallback 금지 테스트를 둔다.

ID/SHA/storage URI/raw Neo4j label은 접힌 `기술 정보`에서만 표시한다.

## 12. Project Structure source tree

root는 6개다.

```text
본문
도판 / 사진
도면
원천 자료
검수 세트
고고학 객체
```

`원천 자료` 아래는 persistent node가 아닌 derived category group이다.

```text
본문 원본
도면 원본
조판 원본
링크 사진
기타
```

각 child는 OriginalAsset이며 저장/parse/provenance 상태를 표시한다. 다른 Project의 asset ID는 조회할 수 없다.

Project Structure contract에 `source_asset_group`, `source_kind_group`, `original_asset`을 추가한다.

## 13. TDD acceptance

구현 순서는 4개 vertical slice이며 각 slice는 `RED -> GREEN -> refactor -> commit`이다.

### Slice 1 — timestamps

- createdAt/updatedAt domain/API
- create stores both
- newest-first/null-last stable order
- structural mutations update updatedAt
- frontend renders backend order 그대로

### Slice 2 — visibility

- semantic CSS classes
- no visibility-critical inline styles
- refresh/open visible in base render
- focus/base CSS contract
- navigation regression 없음

### Slice 3 — semantic graph

- archaeology labels
- missing metadata => semantic fallback, never ID prefix
- Korean known-edge labels
- raw ID only in technical details
- ProjectStructure backend labels도 ID fallback 금지

### Slice 4 — OriginalAsset provenance

필수 tests:

- root symlink allowed / boundary escape rejected
- HWP/HWPX/AI/INDD/JPG/PNG/TIFF OriginalAsset storage
- filename-only AI creates no Drawing
- AI internal identifier is metadata only
- `_45.JPG` mapping 없으면 unlinked
- manifest requires documentVersionId scope
- cross-project/missing/ambiguous target => no edge
- same path/hash idempotent; changed bytes => new asset
- Real Neo4j `HAS_ORIGINAL_ASSET`
- `DERIVED_FROM.method != filename_match`
- Case 6 `Reference(45)->RESOLVES_TO->canonical` unchanged
- `_91.JPG` cannot repair missing Plate 91
- scoped manifest 후에만 `DERIVED_FROM`
- Project Structure `원천 자료` lazy tree

## 14. CI gate

최종 HEAD는 모두 GREEN이어야 한다.

```text
backend hermetic full suite
Real Neo4j integration/E2E
frontend typecheck
frontend unit tests
frontend production build
strict ReviewRound /runs contract
Case 6 canonical regression
OriginalAsset provenance regression
```

실패 테스트를 `--deselect`로 숨기지 않는다.

## 15. Out of scope

- native INDD layout parsing
- HWP/HWPX full parser 신규 개발
- AI source만으로 canonical Drawing 생성
- filename auto-link mode
- manifest auto expert approval
- source upload/write UI
- Project Structure edit/delete/relink
- source photo를 VLM canonical ground truth로 사용
- VLM 10-case PASS 재선언

## 16. 최종 P0 판단

고고학자는 Project Structure에서 publication/canonical 자료와 original source를 명확히 구분하고, 각 source가 `stored but unlinked`인지 explicit provenance로 연결됐는지 확인할 수 있어야 한다.

**filename 숫자, AI filename, Links sequence, VLM 추론 중 하나라도 canonical publication identity를 생성·복구·덮어쓸 수 있으면 전체 remediation은 FAIL이다.**
