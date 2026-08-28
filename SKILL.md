---
name: pknuai-apply
description: 부경대(PKNU) 비교과 프로그램을 예약해 두고 모집이 열리는 순간 자동으로 신청한다. 프로그램 검색·조건 확인(모집기간·정원·설문·팀/외부 신청 여부)·예약·신청서식 첨부·감시자(백그라운드 자동 시작) 설치·신청 결과 확인까지. 트리거 — "비교과 예약", "비교과 자동 신청", "비교과 찾아줘", "pknuai", "선착순 비교과", "비교과 신청됐어?", "비교과 감시자", "extracurricular PKNU apply".
---

# 비교과 자동 예약 (pknuai-apply)

부경대 비교과 프로그램은 대부분 **선착순**이라 모집 시작 몇 분 안에 마감된다.
이 스킬은 사용자가 **이름을 지목한 프로그램만** 예약해 두었다가, 그 프로그램 페이지가
직접 공개하는 모집 시작 시각(분 단위)에 깨어나 2초 간격으로 신청을 시도한다.

## 절대 규칙

1. **사용자가 지목하지 않은 프로그램은 절대 예약하거나 신청하지 않는다.** 신청은 취소가
   번거롭고 실제 자리를 차지한다. 검색 결과를 보여주고 어떤 것을 예약할지 확인받는다.
2. **`apply` 명령(즉시 신청)은 사용자가 명시적으로 요청할 때만 실행한다.** 확인만 필요하면
   `apply --dry-run` 또는 `show`를 쓴다.
3. 신청 결과를 보고할 때 **원장(ledger)에 남은 실제 상태만** 말한다. 사이트가 `DONE`을
   돌려줬다는 사실은 첨부파일이 붙었다는 증거가 아니다. 확실하지 않으면 원문 확인을 권한다.

## 명령

스킬 디렉터리에서 실행한다(`./pknuai-apply` = `python3 -m pknuai_apply`).

| 명령 | 하는 일 |
|---|---|
| `./pknuai-apply status` | 세션·감시자·예약·처리 기록 한눈에 |
| `./pknuai-apply session import` | **로그인된 브라우저에서 세션 자동 추출**(가장 쉬움). Chrome·Edge·Brave·Whale·Firefox |
| `./pknuai-apply session login` | 브라우저를 대신 열어 로그인 후 세션 자동 포착(로그인 전이면 이걸) |
| `./pknuai-apply session set` | Cookie 헤더 직접 붙여넣기(위 방법이 안 될 때). `--clipboard`, `--file`, `--stdin` |
| `./pknuai-apply session check` | 저장된 세션이 아직 유효한지 pknuai에 직접 확인 |
| `./pknuai-apply list [검색어]` | 프로그램 목록(최신순). `--json`, `--pages N` |
| `./pknuai-apply show <코드>` | 그 프로그램의 모집기간·상태·설문/팀/외부 여부·지금 신청 가능 여부 |
| `./pknuai-apply reserve <코드> [--attach 파일]` | 예약. 첨부가 필요한 프로그램은 파일을 같이 넣는다 |
| `./pknuai-apply cancel <코드>` | 예약 취소 |
| `./pknuai-apply apply [코드] [--dry-run]` | 지금 즉시 시도(사용자 요청 시에만) |
| `./pknuai-apply watch [--once]` | 감시자를 이 터미널에서 실행 |
| `./pknuai-apply install-agent` | 감시자를 로그인 자동 시작으로 등록(macOS launchd / Linux systemd) |
| `./pknuai-apply serve` | 로컬 웹 화면(기본 http://127.0.0.1:8765) |
| `./pknuai-apply logs -n 50` | 감시자 기록 |

## 처음 쓰는 사용자를 도울 때

1. `./pknuai-apply status` 로 세션과 감시자 상태를 먼저 본다.
2. 세션이 없으면 — **쿠키를 손으로 복사하게 하지 말 것.** 순서대로 시도한다:
   - 이미 브라우저에 pknuai 로그인이 있으면 `./pknuai-apply session import`. 브라우저 쿠키
     저장소에서 pknuai 세션만 뽑아 검증·저장한다. macOS는 **첫 실행 때 키체인 팝업**이
     한 번 뜨는데 '허용'을 누르면 된다(Chrome Safe Storage 키를 읽기 위함).
   - 로그인 전이면 `./pknuai-apply session login`. 브라우저를 pknuai 로그인 페이지로 열어주고,
     사용자가 **휴대폰 인증까지** 마치면 세션을 자동으로 포착한다. 자격증명은 절대 묻지 않는다.
   - 위 방법이 안 되면 그때만 `session set`(Cookie 헤더 붙여넣기)로 안내한다.
   (포털 로그인은 휴대폰 인증으로 끝나 자동화가 대신 로그인할 수 없다. 세션은 사용자
   컴퓨터의 데이터 디렉터리에 0600으로만 저장되고 밖으로 나가지 않는다.)
3. 감시자가 미등록이면 `./pknuai-apply install-agent` 를 권한다. **예약만 해두고 감시자가
   없으면 아무 일도 일어나지 않는다** — 이 점을 반드시 말해준다.
4. 웹 화면을 원하는 사용자에게는 `./pknuai-apply serve` 를 띄워주고 주소를 알려준다.

## 자동으로 신청하지 않는 경우 (설계된 동작)

| 표시 | 뜻 | 사용자에게 할 말 |
|---|---|---|
| `not_open` | 아직 모집 시작 전 | 정상. 그 시각에 자동으로 시도한다 |
| `window_closed` | 모집 마감 | 예약이 해제된다. 다른 회차를 찾아야 한다 |
| `team` | 팀 신청 프로그램 | 팀 구성이 필요해 자동 신청 대상이 아니다 |
| `survey` | 설문 응답 필요 | 사람이 직접 응답해야 하므로 원문에서 신청 |
| `external` | 외부 사이트에서 신청 | pknuai 버튼만 누르면 실제 등록이 안 된다. 링크로 안내 |
| `enrolled` | 이미 신청/수강 중 | 이미 자리를 잡았다 |
| `attachment_missing` | 신청서식 필요 | `reserve --attach <파일>` 로 파일을 넣으면 자동 신청된다 |
| `login_required` | 세션 만료 | 쿠키를 다시 저장해야 한다 |

## 자주 나오는 상황

- **"예약했는데 신청이 안 됐어"** → `status` 로 감시자가 실행 중인지, `logs` 로 마지막 판정이
  무엇인지 본다. 감시자 미실행이 가장 흔한 원인이다.
- **"세션이 자꾸 풀려"** → pknuai 세션은 몇 시간~하루면 만료된다. 예약 전날/당일에
  `session check` 로 확인하고 필요하면 다시 저장하도록 안내한다.
- **"첨부가 들어갔는지 모르겠어"** → 자동화로 확인할 방법이 없다(학생 화면에 첨부 조회 API가
  없다). 마이페이지에서 사용자가 직접 확인하도록 안내한다.
- **여러 대에서 쓰고 싶다** → 세션·예약은 기기별로 따로 저장된다. 감시자는 한 대에서만 켜는 것이 좋다.

## 데이터 위치

`~/.local/share/pknuai-apply/` (환경변수 `PKNUAI_APPLY_HOME` 로 변경 가능)
— `session.json`(0600), `reservations.json`, `applications.json`(원장), `deferred.json`,
`attachments/`, `watch.log`. 지우려면 `uninstall-agent` 후 이 디렉터리를 삭제하면 된다.
