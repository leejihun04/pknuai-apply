# 비교과 자동 예약 (pknuai-apply)

부경대(PKNU) 비교과 프로그램은 대부분 선착순이라 모집이 열리고 몇 분이면 마감됩니다.
이 도구는 **원하는 프로그램을 미리 예약**해 두면, 그 프로그램 페이지가 공개하는
**모집 시작 시각(분 단위)**에 깨어나 2초 간격으로 신청을 시도합니다. 신청서식 파일도
같이 올려둘 수 있습니다.

- 파이썬 표준 라이브러리만 씁니다. `pip install` 이 필요 없습니다 (Python 3.9+).
- 데이터는 전부 내 컴퓨터에만 저장됩니다. 서버로 보내는 것은 pknuai 요청뿐입니다.
- 터미널로도, 로컬 웹 화면으로도 쓸 수 있습니다.

## 설치

```bash
# 방법 1 — Claude Code 스킬로 설치 (현재 프로젝트의 .claude/skills/ 아래)
npx github:leejihun04/pknuai-apply

# 방법 2 — 내 계정 전체에서 쓰기
git clone https://github.com/leejihun04/pknuai-apply ~/.claude/skills/pknuai-apply

# 방법 3 — 그냥 도구로만 쓰기
git clone https://github.com/leejihun04/pknuai-apply && cd pknuai-apply
```

설치한 폴더에서 `./pknuai-apply <명령>` 으로 실행합니다.

## 처음 한 번: 로그인 세션 저장

포털 로그인은 휴대폰 인증(mSABER/FIDO)으로 끝나서 프로그램이 대신 로그인할 수 없습니다.
브라우저에서 한 번 로그인한 세션을 넘겨주면 됩니다.

1. 브라우저에서 [비교과 프로그램 목록](https://pknuai.pknu.ac.kr/web/nonSbjt/program.do?mId=216)에 로그인
2. 개발자도구(F12) → **네트워크** 탭 → 새로고침 → `program.do` 요청 클릭
3. 요청 헤더의 **Cookie** 값 전체를 복사
4. 아래 명령에 붙여넣기 (화면에 표시되지 않습니다)

```bash
./pknuai-apply session set          # 붙여넣기
./pknuai-apply session set --clipboard   # 복사해 둔 값을 바로 사용
./pknuai-apply session check        # 아직 유효한지 확인
```

세션은 `~/.local/share/pknuai-apply/session.json` 에 **0600(본인만 읽기)** 으로 저장됩니다.
보통 몇 시간~하루면 만료되므로, 중요한 모집 전날에 `session check` 를 한 번 해두세요.

## 예약하기

```bash
./pknuai-apply list 멘토링                  # 검색해서 코드 확인
./pknuai-apply show N202608050              # 모집기간·신청 조건 확인
./pknuai-apply reserve N202608050           # 예약
./pknuai-apply reserve N202608050 --attach ~/신청서식.hwp   # 신청서식이 필요한 경우
./pknuai-apply status                       # 예약 현황과 개시까지 남은 시간
./pknuai-apply cancel N202608050            # 예약 취소
```

## 감시자 켜기 (중요)

**예약만 해두고 감시자가 없으면 아무 일도 일어나지 않습니다.**

```bash
./pknuai-apply install-agent     # 로그인할 때마다 자동 시작 (macOS launchd / Linux systemd)
./pknuai-apply status            # "감시자 ✅ 실행 중" 확인
./pknuai-apply logs -n 50        # 무엇을 하고 있는지
./pknuai-apply uninstall-agent   # 해제
```

터미널에서 직접 돌리려면 `./pknuai-apply watch` (창을 닫으면 멈춥니다).

감시자는 모집 시작 전까지는 거의 아무 요청도 보내지 않고 자다가, 공개된 개시 시각
2초 전에 깨어나 2초 간격으로 두드립니다. 3분이 지나도 열리지 않으면(정원 마감 등)
30초 간격으로 물러납니다.

## 웹 화면

```bash
./pknuai-apply serve            # http://127.0.0.1:8765
```

검색·예약·첨부 업로드·즉시 시도를 브라우저에서 할 수 있습니다. 서버는 이 컴퓨터에서만
접속되고, 다른 사이트가 몰래 조작하지 못하도록 Host/Origin/전용 헤더를 검사합니다.
pknuai 쿠키는 브라우저로 내려보내지 않습니다.

## 자동으로 신청하지 않는 경우

안전을 위해 다음은 **일부러** 사람에게 넘깁니다.

| 상태 | 뜻 |
|---|---|
| `team` | 팀 신청 프로그램 |
| `survey` | 신청 전에 설문 응답이 필요한 프로그램 |
| `external` | 실제 신청은 외부 사이트에서 받는 프로그램 (pknuai 버튼만 누르면 등록이 안 됩니다) |
| `attachment_missing` | 신청서식이 필요한데 올려둔 파일이 없음 |
| `not_open` / `window_closed` | 아직 모집 전 / 이미 마감 |
| `enrolled` | 이미 신청했거나 수강 중 |

또한 프로그램 페이지가 공개한 **모집기간을 내 컴퓨터 시계와 대조**해서, 시작 전이나
마감 후에는 신청 요청 자체를 보내지 않습니다. 한 번 신청한 프로그램은 원장에 기록되어
다시 신청되지 않습니다.

## 데이터와 삭제

```
~/.local/share/pknuai-apply/
├── session.json        # pknuai 쿠키 (0600)
├── reservations.json   # 예약
├── applications.json   # 신청 원장 (중복 신청 방지)
├── deferred.json       # 마지막 판정
├── attachments/        # 올려둔 신청서식
└── watch.log           # 감시자 기록
```

`PKNUAI_APPLY_HOME` 환경변수로 위치를 바꿀 수 있습니다.
완전히 지우려면 `./pknuai-apply uninstall-agent` 후 위 디렉터리를 삭제하세요.

## 설정값 (환경변수)

| 이름 | 기본값 | 뜻 |
|---|---|---|
| `PKNUAI_RESERVATION_BURST_SECONDS` | 2 | 개시 직후 재시도 간격(초) |
| `PKNUAI_RESERVATION_BURST_WINDOW` | 180 | 그 간격을 유지하는 시간(초) |
| `PKNUAI_RESERVATION_CHECK_INTERVAL` | 30 | 평상시 확인 간격(초) |
| `PKNUAI_LIST_PAGES` | 3 | 읽어올 목록 페이지 수 |
| `PKNUAI_WEB_PORT` | 8765 | 웹 화면 포트 |

## 테스트

```bash
cd tests && python3 -m unittest discover -s . -t .
```

## 유의사항

- 내 계정으로 내 자리를 잡는 도구입니다. 남의 계정으로 쓰지 마세요.
- 대학 서버에 무리를 주지 않도록 요청 빈도에 상한을 두었습니다. 이 값을 크게 올리지 마세요.
- 신청 취소는 이 도구가 하지 않습니다. pknuai 마이페이지에서 직접 취소하세요.
- 첨부파일이 실제로 붙었는지는 자동으로 확인할 수 없습니다(학생 화면에 조회 API가 없습니다).
  중요한 신청은 마이페이지에서 눈으로 확인하세요.
