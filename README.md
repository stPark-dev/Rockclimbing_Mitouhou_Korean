<p align="center"><img src="alps_cover_ko.png" alt="락클라이밍 미답봉에의 도전 알프스 편 한글화" width="480"></p>

# 락클라이밍 미답봉에의 도전 알프스 편 한글화

플레이스테이션용 『ロッククライミング 未踏峰への挑戦 アルプス編』(일본판, SLPS-00662, ⓒ 위넷)의 한글 패치 제작 프로젝트입니다.

> **현재 상태: v1.0-beta.1 (AI 검수 + 사용자 결정 반영, 정식 승인 전)**
> 본편 텍스트 1,469단위와 주요 그림 글자·이름 입력을 한글화했습니다. 번역은 AI 일괄 검수만 거쳤고 사람이 승인한 것은 아닙니다(D14). 알려진 문제는 아래에 적었습니다.

## 진행 상황

| 항목 | 상태 |
|---|---|
| 디스크 구조·재구성 | 완료. 데이터 트랙 파일을 제자리에서 바꾸고, 무변경 재구성이 원본과 바이트 단위로 일치 |
| 글꼴·문자 코드 | 12×12 글꼴 1,348자, 1·2바이트 코드, 글자별 진행폭 표(원작의 2바이트 폭 k+1 버그 포함) 해독 |
| 한글 표시 PoC | 완료. 데이터베이스 설명문 한 줄 한국어 표시 |
| 문자표 | 완료. 1,348칸 전부 (문맥 교정 30칸, 미검증 5칸) |
| 문자열 추출 | 모집단 채택: 4,556개(원문 기준 1,474개, 약 6.7만 자). 런타임 대조로 누락 확인 남음 |
| 번역 | 1,469/1,474단위(남은 5는 비텍스트). AI 검수 완료 1,460, 문맥 확인 필요 9(`text/review_ai_v1.json`, D14·D15) |
| 그림 글자 | 일본어 그림 한글화(D1, D11–D13). 타이틀 로고·메뉴 버튼·등반 화면·날씨 아이콘·설명 사진 |
| 이름 입력 | 3쪽 한글 음절표(D10). 입력·저장·불러오기 화면 확인 |

자세한 조사 결과와 근거는 [`docs/survey.md`](docs/survey.md), 결정 사항은 [`docs/decisions.md`](docs/decisions.md)에 있습니다. 현재 상태와 다음 작업 순서는 [`docs/HANDOFF.md`](docs/HANDOFF.md)에 정리되어 있습니다.

## 지원 원본

정당하게 소유한 일본판 디스크 이미지(bin/cue 22트랙, 트랙 1 `MODE2/2352`, 트랙 2–22 CD-DA)만 지원합니다. 원본 이미지와 게임 데이터는 이 저장소에 없으며 배포하지 않습니다.

| 항목 | 값 |
|---|---|
| 트랙 1 크기 | 150,744,384 바이트 |
| 트랙 1 SHA-256 | `86918cf6ae389bd0ef5ab264a0f172d8fcb9d70026a2f25cb7ec3fa9d4b9c6d8` |
| 트랙 1 MD5 | `f4f8bbfd2913d2c92ecc983193aacf29` |

패치는 트랙 1만 바꿉니다. 오디오 트랙은 원본을 그대로 씁니다.

## 패치 적용 (v1.0-beta.1)

1. 위 해시와 같은 트랙 1 이미지를 준비합니다.
2. PPF 3.0 패처(PPF-O-Matic, ApplyPPF 등)로 `RockClimbing_Mitouhou_KO_v1.0-beta.1.ppf`를 트랙 1에 적용합니다. 패치는 원본의 일부 바이트를 검사하므로 다른 이미지에는 적용되지 않습니다.
3. cue와 오디오 트랙(2–22)은 원본 그대로 씁니다.

### v1.0-beta.1 알려진 문제

- 번역은 AI 검수와 용어 결정(D15–D17)만 거쳤고 사람 승인은 아직입니다. v1.0-beta.1 배포본에는 정식판 검수 대상 9단위가 남아 있으며, 저장소에서는 모두 결정되었습니다(暗闇の掘 → 「어둠의 벽」 등, 다음 배포에 반영).
- 화면에서 재지 않은 창의 줄 44개가 원문 최장 줄보다 넓어 잘릴 수 있습니다.
- 영상(STR) 안의 일본어 글자는 그대로입니다(v1.1).
- 이동 장면의 시간 상자·날씨 아이콘(G2·J2)과 일부 스테이지 화면은 실기에서 보지 못했습니다.
- 이전 개발 빌드로 만든 세이브의 이름은 글자가 한 칸씩 밀려 보입니다(이름 번호 141을 선택지 커서로 되돌림).
- 「NEW GAME」 「SAVE GAME」 「MEMORY CARD」 등 원작의 영어 버튼은 그대로 두었습니다.

## 개발 환경

Python 3와 numpy가 필요합니다. 한글 글꼴은 [Galmuri](https://github.com/quiple/galmuri)의 `Galmuri11.bdf`를 씁니다(기본 경로 `../galmuri/`, 또는 환경 변수 `GALMURI11_BDF`).

### 파일 추출 (분석용)

```sh
cd tools
python3 extract.py "../original/<원본> (Track 01).bin" ../work/files
```

### PoC 빌드

```sh
cd tools
python3 poc_db.py --src "../original/<원본> (Track 01).bin" --cue "../original/<원본>.cue" \
  --galmuri ../../galmuri/Galmuri11.bdf --out ../build/poc_db.bin
```

`build/poc_db.cue`가 함께 생기며, 오디오 트랙은 `original/`의 파일을 가리킵니다. 원본 해시가 다르거나 출력 경로가 원본과 같으면 빌드를 거부합니다.

### 배포 빌드와 패치

```sh
cd tools
python3 build_ko.py --src "../original/<원본> (Track 01).bin" --cue "../original/<원본>.cue" \
  --galmuri ../../galmuri/Galmuri11.bdf --ko ../text/ko --out ../build/mitouhou_ko_beta.bin --policy beta \
  --title-logo ../work/assets/title_logo_ko.png --db-photos ../work/assets/db_photo1_ko.png ../work/assets/db_photo2_ko.png
python3 ppf.py "../original/<원본> (Track 01).bin" ../build/mitouhou_ko_beta.bin ../build/RockClimbing_Mitouhou_KO_v1.0-beta.1.ppf
```

`--policy dev`는 초벌을 포함한 배포 불가 빌드, `beta`는 AI 검수 이상만, `release`는 사람 승인만 받습니다. 타이틀 로고와 설명 사진 그림은 저장소 밖(`work/assets/`)에 둡니다.

### 테스트

```sh
python3 -m pytest -q tests/
```

원본 데이터가 필요한 테스트는 `original/`에 원본 트랙, `work/files/`에 추출 파일이 있을 때만 실행됩니다.

## 구조

| 경로 | 내용 |
|---|---|
| `tools/iso.py`, `tools/cdsector.py` | 트랙 1 ISO 9660 파일 제자리 교체, Mode 2 Form 1 EDC/ECC |
| `tools/textcodec.py` | 게임 문자 코드 ↔ 글리프 번호 |
| `tools/kfont.py` | BDF → 게임 12×12 글리프 |
| `tools/extract.py` | 데이터 트랙 파일 추출 |
| `tools/poc_db.py` | 대표 PoC 빌더 |
| `tools/charmap.py`, `tables/charmap.tsv` | 글리프 번호 → 문자표 (판독 상태 포함) |
| `tools/textmap.py` | 문자열 모집단 추출 → `text/src/` (원문, 저장소 제외) |
| `tools/units.py`, `tools/kocheck.py` | 번역 단위 파일 `text/ko/` 생성, 번역 기계 검사 |
| `tools/build_ko.py` | 제품 빌드(글꼴 칸 배정·글리프·진행폭·문자열 제자리 쓰기). `--policy dev|beta|release` |
| `tools/graphics.py`, `tools/nameentry.py`, `tools/lz74.py` | 그림 글자, 한글 이름 입력, 그림 압축 |
| `tools/ppf.py` | 배포용 PPF 3.0 패치 생성·적용 검증 |
| `text/glossary.json` | 용어집 |
| `docs/` | 조사 기록, 결정 기록 |

디스크 도구는 같은 제작자의 [바람의 검심 한글화](https://github.com/stPark-dev/Kenshin_Juuyuushi_Inbou_Hen_Korean) 프로젝트에서 가져와 이 디스크에 맞게 고쳤습니다.
