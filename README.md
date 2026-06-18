# LoL 팀 경매

강사님이 참가자와 팀장을 등록하고, 팀장별 예산으로 실시간 입찰하는 League of Legends 내전용 경매 MVP입니다.

## 실행

```bash
docker compose up --build
```

브라우저에서 `http://localhost:8000`을 엽니다.

## Vercel 배포

프로젝트에는 `api/index.py`와 `vercel.json`이 포함되어 있습니다.

```bash
vercel --prod
```

Vercel Functions는 WebSocket 연결을 유지하지 않으므로 배포판에서는
1초 간격 상태 조회를 사용합니다. 영속 운영을 위해 Vercel 프로젝트에
Upstash Redis를 연결하고 다음 환경변수를 설정해야 합니다.

```env
UPSTASH_REDIS_REST_URL=...
UPSTASH_REDIS_REST_TOKEN=...
```

Redis가 없으면 Vercel의 임시 파일 저장소를 사용하므로 상태가 초기화될 수
있으며 화면 상단에 경고가 표시됩니다.

Riot API 조회를 사용하려면 프로젝트 루트에 `.env`를 만들고 키를 넣습니다.

```env
RIOT_API_KEY=RGAPI-...
HOST_PIN=원하는강사님PIN
SESSION_SECRET=충분히긴임의문자열
```

키가 없어도 참가자를 직접 입력해 전체 경매 기능을 사용할 수 있습니다.

## 현재 포함된 규칙

- 팀장마다 서로 다른 시작 예산 설정
- 강사님·팀장·참가자 역할별 입장 및 PIN 권한 분리
- 등록된 참가자 중 팀장을 지정하고 본인 주 포지션에 자동 배치
- 참가자 소개 페이지와 티어 엠블럼
- 참가자별 점수제 점수 입력
- 참가자가 직접 TOP/JUG/MID/ADC/SUP 5인 팀 등록
- 강사님이 점수제 팀 총점 제한 설정
- 팀 등록 시 점수 초과·선수 중복·포지션 적합성 검사
- 강사님 승인 팀 대상 무작위 단판 토너먼트 대진표
- 경기 승자 선택 시 다음 라운드 자동 진출
- 강사님이 여러 대회를 생성하고 현재 대회 선택
- 참가자·경매·등록 팀·대진표를 대회별로 완전히 분리
- 대회 삭제 시 해당 대회의 모든 관련 데이터 일괄 삭제
- 참가자 주/부 포지션: TOP, JUG, MID, ADC, SUP
- 경매 시작 시 참가자 순서 무작위 확정
- 팀장이 입찰 점수를 직접 입력
- 강사님 설정 카운트다운 및 막판 입찰 시간 연장
- 타이머 종료 시 자동 낙찰, 예산 자동 차감
- 무입찰 참가자는 별도 유찰 명단으로 이동
- 1차 경매 종료 후 강사님이 유찰자 재경매 시작
- 실시간 WebSocket 화면 동기화
- JSON 파일 영속화 및 Docker 볼륨

기본 강사님 PIN은 로컬 개발용 `1234`입니다. 외부에 배포할 때는 반드시
`.env`의 `HOST_PIN`과 `SESSION_SECRET`을 변경하세요.

## 개발 실행

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\uvicorn app.main:app --reload
```

엔진 테스트:

```bash
python -m unittest discover -s tests
```
