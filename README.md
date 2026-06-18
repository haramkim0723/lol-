# LoL 팀 경매

호스트가 참가자와 팀장을 등록하고, 팀장별 예산으로 실시간 입찰하는 League of Legends 내전용 경매 MVP입니다.

## 실행

```bash
docker compose up --build
```

브라우저에서 `http://localhost:8000`을 엽니다.

Riot API 조회를 사용하려면 프로젝트 루트에 `.env`를 만들고 키를 넣습니다.

```env
RIOT_API_KEY=RGAPI-...
```

키가 없어도 참가자를 직접 입력해 전체 경매 기능을 사용할 수 있습니다.

## 현재 포함된 규칙

- 팀장마다 서로 다른 시작 예산 설정
- 참가자 주/부 포지션: TOP, JUG, MID, ADC, SUP
- 경매 시작 시 참가자 순서 무작위 확정
- 팀장이 입찰 점수를 직접 입력
- 호스트 설정 카운트다운 및 막판 입찰 시간 연장
- 타이머 종료 시 자동 낙찰, 예산 자동 차감
- 무입찰 참가자는 별도 유찰 명단으로 이동
- 1차 경매 종료 후 호스트가 유찰자 재경매 시작
- 실시간 WebSocket 화면 동기화
- JSON 파일 영속화 및 Docker 볼륨

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
