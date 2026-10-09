# epub2xtch

EPUB을 **XTEink X3 / X4**의 네이티브 포맷(**XTC 1비트 / XTCH 2비트**)으로 바꾸는 로컬 변환기입니다. macOS 네이티브(Calibre 불필요), 오프라인으로 처리합니다.

- 순수 파이썬(PyMuPDF + Pillow + numpy)
- **2비트 XTCH**(4단계 그레이) 지원 — 오픈소스 최초
- 목차·메타데이터 자동 생성, 여백 정규화
- 뷰어 `xtc-view` 포함(기기 없이 미리보기)

> ⚠️ 본인이 소장한 EPUB이나 공개 EPUB에 대해서만 사용이 가능합니다. 도구 사용에 따른 모든 책임과 저작권·라이선스 준수 의무는 사용자에게 있습니다.

## 설치

[uv](https://docs.astral.sh/uv/) 기준입니다.

```bash
uvx --from git+https://github.com/hyunhonoh/epub2xtch epub2xtch 책.epub   # 설치 없이 실행
uv tool install git+https://github.com/hyunhonoh/epub2xtch                # 명령 설치
```

설치하면 `epub2xtch`(변환)와 `xtc-view`(미리보기) 명령이 생깁니다.

## 사용법

```bash
epub2xtch 책.epub                     # 기본값: X3 / 22pt / 2비트 / 좌우 여백 2.5%
epub2xtch 책.epub out.xtc -d x4 -b 1   # X4, 1비트
epub2xtch 책.epub -f 24 --margin 0     # 글자 크게, 상하좌우 끝까지 꽉
epub2xtch 책.epub --invert            # 기기에서 명암이 반전돼 보이면

# 순정 펌웨어 실기 권장 예시(명암 반전 + 넉넉한 글자 + 좁은 줄간격 + 외부 폰트)
epub2xtch 책.epub --invert -f 30 --line-spacing 1.6 --font 폰트.ttf --font-bold 폰트.ttf
```

| 옵션 | 설명 | 기본 |
|---|---|---|
| `-d, --device {x3,x4}` | 대상 기기 (X3=528×792, X4=480×800) | `x3` |
| `-b, --bits {1,2}` | 2=XTCH(4단계), 1=XTC(흑백) | `2` |
| `-f, --fontsize` | 본문 폰트 크기(pt) | `22` |
| `--margin` | 남는 여백 %(상하좌우, 0=끝까지 꽉, 내부 overscan+crop) | `2.5` |
| `--line-spacing` | 줄간격(line-height 배수) 강제. 예 `1.6`(책 줄간격이 넓을 때) | 책 기본 |
| `--no-trim` | 여백 정규화 끄기(책 원본 유지) | 정규화 |
| `--font` / `--font-bold` | 렌더 폰트 직접 지정 | — |
| `--no-font` | MuPDF 내장 폰트로 | — |
| `--invert` | 명암 반전 | — |
| `--no-toc` | 목차 미포함 | 포함 |

## 미리보기

```bash
xtc-view 책.xtc                 # 메타·목차 + 전체를 책.preview.pdf 로
xtc-view 책.xtc --page 20        # 특정 페이지만 PNG
xtc-view 책.xtc --invert-preview # 명암 반전 확인
```

## 폰트

기본 폰트는 **KoPub World 바탕체**(무료)이며, 처음 실행할 때 **공식 배포처**(<https://www.kopus.org/biz-electronic-font2/>)에서 받아 캐시에 저장합니다. **다운로드·사용 시 폰트 라이선스에 동의하는 것으로 간주합니다.**

- `--no-font` : MuPDF 내장 폰트로(다운로드 안 함)
- `--font 정체.ttf --font-bold 볼드.ttf` : 원하는 폰트 지정 (환경변수 `EPUB2XTCH_FONT` / `EPUB2XTCH_FONT_BOLD` 로 기본값 지정 가능)

## 모듈로 사용

```python
import epub2xtch
epub2xtch.epub_to_xtc("책.epub", "책.xtc", device="x3", bit_depth=2)
```

## 크레딧 · License

XTC/XTCH 포맷은 **CrossPoint Reader**(MIT, © 2025 Dave Allie · <https://github.com/crosspoint-reader/crosspoint-reader>)의 파서를 참고해 독립 구현했습니다. 포맷 상세는 [`src/epub2xtch/core.py`](src/epub2xtch/core.py) 도크스트링에 있습니다.

코드는 MIT입니다. 폰트는 포함하지 않으며 각 폰트 라이선스를 따릅니다.
