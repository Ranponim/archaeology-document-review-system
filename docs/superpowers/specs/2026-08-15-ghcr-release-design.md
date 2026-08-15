# GHCR 릴리스와 Windows 업데이트 설계

## 목적

Windows Docker Desktop에서 실행하는 단일 사용자용 검수 도구를 GitHub Release로
배포한다. 릴리스는 검증된 컨테이너 이미지를 GitHub Container Registry(GHCR)에
게시하고, 사용자 PC는 명시적인 업데이트 명령으로만 새 버전을 적용한다.

## 범위와 비범위

- 범위: GitHub Actions CI/이미지 게시, 불변 버전 태그, Windows 업데이트·상태 확인·
  실패 시 이전 버전 복구, 운영 문서.
- 비범위: self-hosted runner, PC 원격 배포, 자동 갱신 에이전트, Docker Hub 동시 게시,
  원본 문서·Neo4j 데이터의 클라우드 전송.

## 아키텍처

```text
GitHub Release vX.Y.Z
  -> Actions: 정적 검사와 테스트
  -> Actions: Docker 이미지 build / GHCR publish / provenance attest
  -> GHCR: ghcr.io/ranponim/archaeology-document-review-system:vX.Y.Z
  -> Windows update.ps1: pull -> compose up -d -> health check
```

Compose는 `APP_IMAGE_TAG`로 `web`과 `worker`의 같은 릴리스 이미지를 선택한다.
`latest`는 최신 성공 릴리스만 가리키는 편의 태그이며, 설치·롤백의 기준은 항상
불변 `vX.Y.Z` 태그다.

## Release workflow

- 트리거는 GitHub Release의 `published` 이벤트다. prerelease는 같은 방식으로
  `vX.Y.Z-rc.N` 불변 태그만 만들고 `latest`는 갱신하지 않는다.
- 먼저 backend test, Compose 계약 검사, Docker build를 수행한다. 모두 성공한 경우에만
  GHCR에 push한다.
- 이미지 이름은 `ghcr.io/<repository-owner>/archaeology-document-review-system`이다.
- workflow 권한은 `contents: read`, `packages: write`, attestation에 필요한
  `attestations: write`, `id-token: write`로 제한한다. 액션은 커밋 SHA로 고정한다.
- GitHub 공개 패키지는 Windows가 인증 없이 pull한다. 비공개 패키지인 경우에만 사용자는
  `read:packages` 범위의 PAT로 `docker login ghcr.io`를 수행하며, PAT는 `.env`나
  앱 로그에 저장하지 않는다.

## Windows 업데이트와 롤백

- `scripts/update.ps1`는 현재 `APP_IMAGE_TAG`를 읽어 별도 상태 파일에 기록하고,
  사용자가 지정한 버전(기본값은 `latest`)을 `docker compose pull` 후 `up -d`로 적용한다.
- `scripts/healthcheck.ps1`는 `http://localhost:8080/health`와 필수 Compose 서비스의
  health 상태를 제한 시간 안에 확인한다.
- health check가 실패하면 update script가 기록한 이전 불변 태그로 compose를 다시
  기동하고 non-zero로 종료한다. 이전 태그가 없으면 실패 사실만 보고하고 원본/볼륨을
  삭제하지 않는다.
- 업데이트는 `.env`, `review_data`, `neo4j_data`, Redis 볼륨을 삭제·초기화하지 않는다.
  `docker compose down -v`, 데이터 마이그레이션, 원본 파일 변경은 수행하지 않는다.

## 사용자 경험과 오류 처리

- README에 최초 설치, 특정 버전 설치, 최신 안정판 업데이트, 롤백 및 개인 GHCR 로그인
  절차를 제공한다.
- 업데이트 출력은 이미지 태그·서비스 상태·안전한 오류만 표시하며 API key, 원본 URI,
  해시, 파일 바이트를 표시하지 않는다.
- 웹 UI의 업데이트 버튼은 이 단계에서 만들지 않는다. Windows 명령은 명시적 사용자
  실행이므로 업무 중 자동 재기동하지 않는다.

## 검증 기준

- workflow 파일은 Release trigger, 최소 권한, SHA-pinned actions, GHCR tags와 테스트
  선행 조건을 정적 테스트로 검증한다.
- PowerShell 스크립트는 태그 검증, 이전 태그 기록, 실패 롤백 명령과 볼륨 비삭제를
  mock 기반 테스트로 검증한다.
- Compose smoke는 버전 태그가 `web`과 `worker`에 같은 값으로 전달되고 health endpoint가
  실제 FastAPI에서 응답함을 확인한다.
