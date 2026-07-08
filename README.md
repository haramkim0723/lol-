# LoL 내전 운영 시스템

League of Legends 내전을 위한 경매제·점수제 대회 운영 웹앱이야.

- 서비스: [lol-auction-delta.vercel.app](https://lol-auction-delta.vercel.app)
- 전체 사용 설명서: [운영 설명서](docs/USER_GUIDE.md)

## 주요 기능

- 경매제 대회와 점수제 대회를 각각 생성·관리
- 강사님·팀장·참가자 역할별 화면과 권한 분리
- 참가자 티어, 주/부 포지션, 포지션별 점수 관리
- 이름 또는 Riot ID 참가자 검색
- 팀 조합 시뮬레이션과 제한 점수 기반 추천
- 참가자의 5인 팀 등록과 강사님 승인
- 승인 팀 토너먼트 대진표 및 승자 자동 진출
- 팀장별 예산과 PIN을 사용하는 실시간 경매
- 팀장 접속 확인 후 후보별 타이머 시작
- 자동 낙찰, 예산 차감, 유찰 및 재경매
- 여러 대회의 데이터 독립 관리

## 가장 빠른 사용 순서

1. 서비스에 접속해 `강사님`으로 입장해.
2. `강사님 설정`에서 경매제 또는 점수제 대회를 생성해.
3. 참가자와 주/부 포지션 점수를 등록해.
4. 경매제라면 팀장과 예산을 지정하고 `경매장`을 열어.
5. 점수제라면 총점 제한을 정하고 참가자에게 팀 등록 주소를 공유해.

화면별 자세한 사용법과 운영 순서는 [운영 설명서](docs/USER_GUIDE.md)를 참고해.

## 로컬 실행

### Docker

```bash
docker compose up --build
```

브라우저에서 `http://localhost:8000`을 열어.

### Python

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\uvicorn app.main:app --reload
```

## 환경변수

`.env.example`을 참고해 설정해.

```env
RIOT_API_KEY=
DATA_FILE=/data/state.json
SCRIM_DATABASE_URL=postgresql://...
STATE_DATABASE_URL=
STATE_DATABASE_KEY=lol-auction:state
SCRIM_ADMIN_PASSWORD=1234
SCRIM_SESSION_SECRET=충분히-긴-임의-문자열
UPSTASH_REDIS_REST_URL=
UPSTASH_REDIS_REST_TOKEN=
STATE_REDIS_KEY=lol-auction:state
```

로그인은 본 Riot ID + 비밀번호 계정 하나로 통합돼 있어. 공개 회원가입은 기본 차단되고, 강사님이 `/members`에서 회원을 생성해. 새 회원의 기본 비밀번호는 `1234`이고, 본 아이디와 부 아이디를 따로 관리할 수 있어. 운영 환경에서는 반드시 `SCRIM_ADMIN_PASSWORD`와 `SCRIM_SESSION_SECRET`을 변경해.

`SCRIM_DATABASE_URL`을 설정하면 회원/스크림 DB와 대회 상태가 같은 외부 Postgres에 저장돼. 대회 상태만 별도 DB로 분리하려면 `STATE_DATABASE_URL`을 추가로 설정해.

## 더미 데이터

포지션별 5명, 총 25명의 점수제 참가자를 생성해. 주 포지션과 부 포지션 점수가 서로 다르게 구성돼.

```powershell
.\.venv\Scripts\python.exe scripts\seed_dummy_data.py
```

기존 `data/state.json`이 있으면 `data/state.before-dummy.json`으로 백업해.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
node --check app\static\app.js
```

## Vercel 배포

```bash
npx vercel --prod --yes
```

Vercel에서는 WebSocket 대신 1초 간격 자동 갱신을 사용해. 데이터를 안정적으로 유지하려면 `SCRIM_DATABASE_URL`에 외부 Postgres를 연결해.
