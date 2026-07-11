# Feature And API Flow Scenarios

이 문서는 운영자가 기능을 점검할 때 따라갈 전체 시나리오와 API 호출 흐름을 정리한다.

## 1. 로그인과 권한

### 강사님 로그인
1. `GET /`로 SPA 진입
2. `POST /api/scrim/auth/login`
3. `GET /api/state`
4. 기대 결과
   - `viewer.authenticated = true`
   - `viewer.role = host`
   - 강사님 전용 메뉴 노출

### 참가자 로그인
1. `POST /api/scrim/users` 또는 강사님이 `POST /api/scrim/admin/users`
2. `POST /api/scrim/auth/login`
3. `GET /api/scrim/me`
4. `GET /api/state`
5. 기대 결과
   - 일반 참가자는 강사님 설정, 회원 관리, 참가 승인 메뉴 접근 불가
   - 본인의 참가 신청, 팀 등록, 마이페이지 접근 가능

## 2. 대회 관리

### 대회 생성
1. 강사님 로그인
2. `POST /api/competitions`
3. `GET /api/state`
4. 기대 결과
   - 새 대회가 현재 대회로 선택됨
   - `competition_registry.active_competition_id`가 새 대회 id
   - 모드에 따라 경매 또는 점수제 화면이 보임

### 대회 선택
1. `POST /api/competitions/{competition_id}/select`
2. `GET /api/state`
3. 기대 결과
   - 현재 대회 상태, 참가 신청, 팀, 스크림 결과가 선택 대회 기준으로 전환됨
   - 회원 관리 전체 회원 목록은 대회와 무관하게 유지됨
   - 회원 관리의 `대회 참가` 컬럼만 현재 대회 기준으로 계산됨

### 대회 삭제
1. `DELETE /api/competitions/{competition_id}`
2. `GET /api/state`
3. 기대 결과
   - 해당 대회의 참가 신청, 팀, 대진, 결과 상태가 제거됨
   - 다른 대회의 데이터는 유지됨

## 3. 포스터와 공지사항

### 포스터 메인
1. 대회 생성 시 `poster_image` 입력
2. `GET /api/state`
3. 기대 결과
   - 현재 대회 포스터가 메인 화면에 표시됨
   - 점수제 참가자 화면에는 포스터가 표시되지 않음

### 공지사항
1. `POST /api/notices`
2. `GET /api/state`
3. `DELETE /api/notices/{notice_id}`
4. 기대 결과
   - 강사님은 작성/삭제 가능
   - 참가자는 읽기만 가능

## 4. 회원 관리와 명단

### 회원 생성과 승인
1. `POST /api/scrim/admin/users`
2. `PATCH /api/scrim/admin/users/{user_id}/approval`
3. `GET /api/roster?filter=all`
4. 기대 결과
   - 승인된 일반 회원은 전역 회원 관리 목록에 표시됨
   - 현재 대회 신청 여부는 `tournament_status`로만 분리됨

### 명단 직접 추가와 저장
1. `POST /api/roster`
2. `PATCH /api/roster/{roster_id}`
3. `PATCH /api/roster`
4. 기대 결과
   - Riot ID가 있으면 계정 발급 상태가 갱신됨
   - 참가라인과 티어가 있으면 포지션 점수가 계산됨
   - 필터 `with_id`, `without_id`, `applied`, `applied_unpaid`, `not_applied`가 현재 대회 기준으로 동작함

### Riot API 조회
1. `POST /api/roster/riot/preview`
2. 기대 결과
   - Riot ID, 티어, 포지션 점수 미리보기 반환
   - Riot API 키가 없거나 Riot ID가 잘못되면 400 또는 설정 오류 반환

## 5. 점수 자동 산출표

### 점수표 수정
1. `PUT /api/roster-score-table`
2. `GET /api/state`
3. 기대 결과
   - 티어별 포지션 점수표가 저장됨
   - 이후 roster 점수 계산과 Riot preview에 반영됨
   - 값이 없으면 기본 점수표로 계산됨

## 6. 참가 신청

### 신청 열기
1. 강사님 `PUT /api/participation/settings`
2. 참가자 `GET /api/state`
3. 기대 결과
   - 신청 약관과 신청 버튼 노출

### 참가자 신청
1. 참가자 로그인
2. `POST /api/participation/apply`
3. `GET /api/participation/applications`
4. 기대 결과
   - 신청자는 승인 대기 명단에 표시
   - 신청하지 않은 인원은 미신청 명단에 표시

### 강사님 승인/거절
1. `PATCH /api/participation/applications/{user_id}`
2. `GET /api/participation/applications`
3. `GET /api/roster?filter=applied`
4. `GET /api/state`
5. 기대 결과
   - 승인 시 점수제 참가자 후보에 동기화
   - 회원 관리와 참가 신청 승인 화면이 현재 대회 기준으로 갱신
   - 거절 후 재신청 가능

## 7. 점수제 참가자와 조합 시뮬레이션

### 점수제 참가자 보기
1. `GET /api/state`
2. 기대 결과
   - 승인된 참가자만 포지션별 카드에 표시
   - 검색과 포지션 필터 동작

### 조합 추천
1. `POST /api/tournament/recommend`
2. 기대 결과
   - 이미 등록된 팀원은 시뮬레이터 후보에서 제외
   - 고정 포지션을 제외한 빈 자리 추천
   - 팀 총점 제한에 가장 가까운 조합 반환

## 8. 팀 등록과 승인

### 참가자 팀 등록
1. 참가자 로그인
2. `POST /api/tournament/teams`
3. `GET /api/state`
4. 기대 결과
   - 5개 포지션이 모두 있어야 등록 가능
   - 팀 점수 제한 초과 시 실패
   - 등록 후 승인 대기 상태

### 강사님 팀 승인/반려/삭제
1. `POST /api/tournament/teams/{team_id}/approval`
2. `DELETE /api/tournament/teams/{team_id}`
3. `GET /api/state`
4. 기대 결과
   - 승인된 팀만 대회 진행과 스크림 결과 입력 후보
   - 삭제된 팀은 대진/결과 대상에서 제외

## 9. 점수제 대회 진행

### 토너먼트 설정
1. `PUT /api/tournament/settings`
2. 기대 결과
   - 총점 제한, 조 편성 여부, 조 수, 조당 진출팀 저장

### 조 편성
1. `POST /api/tournament/start`
2. `PUT /api/tournament/groups/qualifiers`
3. `POST /api/tournament/groups/start-knockout`
4. 기대 결과
   - 조 편성은 시작 버튼에서 실제 랜덤 배치
   - 화면에서는 미리 만들어진 순서를 한 팀씩 공개
   - 체크된 팀이 본선 진출팀으로 반영

### 본선 진행
1. `PUT /api/tournament/bracket`
2. `POST /api/tournament/winner`
3. 기대 결과
   - 강사님 직접 대진 편집 가능
   - 승자 선택 시 다음 라운드 진출
   - 마지막 승자 선택 시 대회 종료와 챔피언 저장

## 10. 스크림 결과와 승률

### 결과 등록
1. `POST /api/scrim/results`
2. `PUT /api/scrim/results/{result_id}`
3. 기대 결과
   - 승인된 팀 또는 강사님만 결과 등록/수정 가능
   - BO3, BO5 모두 허용
   - 무승부 가능
   - 승리 3점, 무승부 1점, 패배 0점 기준으로 그룹 순위 계산
   - 득실차와 전적에 따라 순서 재정렬

## 11. 경매 대회

### 경매 설정과 시작
1. `PUT /api/settings`
2. `POST /api/players`
3. `POST /api/captains`
4. `POST /api/auction/start`
5. `POST /api/auction/timer/start`
6. 기대 결과
   - 강사님만 설정/시작 가능
   - 주장 등록은 실제 회원 계정 Riot ID와 연결
   - 경매 시작 후 선수/주장 설정 변경 제한

### 입찰과 진행 제어
1. 주장 로그인
2. `POST /api/auction/bid`
3. 강사님 `POST /api/auction/pause`
4. 강사님 `POST /api/auction/resume`
5. 필요 시 `POST /api/auction/reauction`
6. 기대 결과
   - 주장은 본인 팀으로만 입찰 가능
   - 예산과 남은 슬롯 최소 비용을 초과하면 거절
   - 일시정지/재개 상태가 모든 화면에 반영

## 12. 스크림 팀 관리

### 팀 생성과 합류
1. `POST /api/scrim/users`
2. `POST /api/scrim/teams`
3. 다른 회원 `POST /api/scrim/teams/join`
4. 기대 결과
   - 팀장은 리더 권한
   - 이미 활성 팀이 있는 회원은 다른 팀 합류 불가

### 일정 등록
1. `POST /api/scrim/schedules`
2. 기대 결과
   - 팀 리더만 일정 생성 가능
   - 시간 겹침은 거절

## 13. 운영 점검 순서

1. 강사님 로그인
2. 새 점수제 대회 생성
3. 참가 신청 열기
4. 회원 10명 생성/승인
5. 참가자 10명 신청
6. 강사님 승인
7. 팀 2개 등록
8. 팀 승인
9. 스크림 결과 등록
10. 조 편성 또는 본선 시작
11. 경기 승자 입력
12. 대회 종료 확인
13. 회원 관리에서 전역 회원은 유지되고 대회 참가 컬럼만 현재 대회 기준인지 확인

## 14. API 테스트 기준

필수 테스트는 다음 흐름을 포함해야 한다.

- 인증: 로그인, 로그아웃, 현재 사용자, 권한 거절
- 대회: 생성, 선택, 삭제, 포스터 포함 생성
- 회원/명단: 회원 생성, 승인, 명단 생성, 단건 수정, 일괄 수정, 필터
- 참가 신청: 신청 열기, 신청, 승인, 거절, 재신청
- 점수표: 점수표 수정 후 roster 점수 반영
- 점수제 팀: 추천, 등록, 승인, 반려, 삭제
- 대회 진행: 조 편성, 진출팀 선택, 본선 편집, 승자 선택
- 스크림 결과: 등록, 수정, BO3/BO5, 무승부
- 경매: 설정, 선수 생성, 주장 생성, 시작, 타이머, 입찰, 일시정지, 재개
- 공지: 생성, 삭제
- 스크림 팀: 팀 생성, 합류, 일정 등록, 겹침 거절

## 15. API Route Inventory

아래 목록은 시나리오 문서가 반드시 포함해야 하는 현재 API 엔드포인트다.

### Core

- `GET /api/state`
- `POST /api/competitions`
- `POST /api/competitions/{competition_id}/select`
- `DELETE /api/competitions/{competition_id}`
- `PUT /api/participation/settings`
- `POST /api/participation/apply`
- `GET /api/participation/applications`
- `PATCH /api/participation/applications/{user_id}`
- `GET /api/members`
- `GET /api/roster`
- `POST /api/roster/import`
- `POST /api/roster`
- `POST /api/admin/setup-test-competitions`
- `POST /api/admin/competitions/{competition_id}/bulk-build-teams`
- `POST /api/roster/riot/preview`
- `PATCH /api/roster/{roster_id}`
- `PATCH /api/roster`
- `PUT /api/settings`
- `POST /api/notices`
- `DELETE /api/notices/{notice_id}`
- `PUT /api/roster-score-table`
- `POST /api/captains`
- `DELETE /api/captains/{captain_id}`
- `POST /api/players`
- `POST /api/players/riot`
- `POST /api/players/riot/preview`
- `DELETE /api/players/{player_id}`
- `PATCH /api/players/{player_id}/score`
- `PUT /api/tournament/settings`
- `POST /api/tournament/recommend`
- `POST /api/tournament/teams`
- `POST /api/tournament/teams/{team_id}/approval`
- `DELETE /api/tournament/teams/{team_id}`
- `POST /api/tournament/start`
- `PUT /api/tournament/groups/qualifiers`
- `POST /api/tournament/groups/start-knockout`
- `PUT /api/tournament/bracket`
- `POST /api/tournament/winner`
- `POST /api/scrim/results`
- `PUT /api/scrim/results/{result_id}`
- `POST /api/auction/start`
- `POST /api/auction/reauction`
- `POST /api/auction/timer/start`
- `POST /api/auction/bid`
- `POST /api/auction/pause`
- `POST /api/auction/resume`
- `POST /api/reset`

### Scrim

- `GET /api/scrim/health`
- `POST /api/scrim/users`
- `POST /api/scrim/auth/login`
- `POST /api/scrim/auth/logout`
- `GET /api/scrim/me`
- `PATCH /api/scrim/me`
- `GET /api/scrim/admin/users`
- `POST /api/scrim/admin/users`
- `PATCH /api/scrim/admin/users/{user_id}/password`
- `PATCH /api/scrim/admin/users/{user_id}/approval`
- `GET /api/scrim/teams`
- `POST /api/scrim/teams`
- `POST /api/scrim/teams/join`
- `POST /api/scrim/schedules`
