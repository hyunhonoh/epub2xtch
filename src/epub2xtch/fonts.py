"""KoPub World 바탕 폰트 — 공식 출처(kopus.org)에서 **동의 후** 내려받아 캐시.

폰트를 패키지에 번들·재배포하지 않는다(라이선스상 프로그램 임베딩은 별도 승인 필요).
대신 첫 실행 때 사용자에게 라이선스를 고지하고 동의를 받은 뒤, **한국출판인회의 공식
배포 zip**에서 바탕체 정체/볼드만 추출해 사용자 캐시에 저장한다. 재배포가 아니라
"사용자가 동의하고 자기 기기에 공식 무료폰트를 받는" 형태다.

- 캐시: $XDG_CACHE_HOME/epub2xtch/fonts (없으면 ~/.cache/epub2xtch/fonts)
- 비대화형(파이프/CI)에서는 다운로드하지 않고 (None, None) → MuPDF 내장 폰트로 폴백
"""
from __future__ import annotations

import io
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

LICENSE_PAGE = "https://www.kopus.org/biz-electronic-font2/"
# 공식 배포 zip (연 단위로 갱신될 수 있음 → 실패 시 위 페이지로 안내)
OFFICIAL_ZIP = "https://www.kopus.org/wp-content/uploads/2026/04/KOPUBWORLD_TTF_FONTS2026.zip"

# zip 내부 파일명 → 캐시 저장명
MEMBERS = {
    "regular": ("KoPubWorld Batang Medium.ttf", "KoPubWorldBatangMedium.ttf"),
    "bold": ("KoPubWorld Batang Bold.ttf", "KoPubWorldBatangBold.ttf"),
}

_LICENSE_NOTICE = f"""\
[epub2xtch] 한글 조판용 기본 폰트로 'KoPub World 바탕체'(한국출판인회의, 무료)를 공식 배포처에서 받아 사용합니다.
  · 공식/라이선스: {LICENSE_PAGE} (정보 등록 후 무료 사용, 폰트 파일 재배포·수정·판매는 별도 조건)
  · 공식 파일을 당신의 기기 캐시로 내려받아 렌더링에만 사용합니다(재배포 아님).
  · 다운로드·사용 시 위 라이선스에 동의하는 것으로 간주합니다. 원치 않으면 --no-font(내장 폰트) 또는 --font 로 지정하세요.
"""


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    d = Path(base) / "epub2xtch" / "fonts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _valid_font(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 100_000:
        return False
    try:
        import pymupdf
        pymupdf.Font(fontfile=str(path))
        return True
    except Exception:
        return False


def cached() -> tuple[str | None, str | None]:
    d = cache_dir()
    reg = d / MEMBERS["regular"][1]
    bold = d / MEMBERS["bold"][1]
    if _valid_font(reg):
        return str(reg), (str(bold) if _valid_font(bold) else None)
    return None, None


def _download_official() -> bool:
    d = cache_dir()
    try:
        print(f"[epub2xtch] 공식 폰트 zip 다운로드: {OFFICIAL_ZIP}", file=sys.stderr)
        with urllib.request.urlopen(OFFICIAL_ZIP) as resp:
            blob = resp.read()
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            names = set(z.namelist())
            for member, saveas in MEMBERS.values():
                if member not in names:
                    print(f"[epub2xtch] zip에 {member} 없음(배포 구성 변경?).", file=sys.stderr)
                    return False
                (d / saveas).write_bytes(z.read(member))
        reg, _ = cached()
        return reg is not None
    except Exception as e:
        print(f"[epub2xtch] 폰트 다운로드 실패: {e}\n"
              f"           공식 페이지에서 직접 받아 --font 로 지정하세요: {LICENSE_PAGE}",
              file=sys.stderr)
        return False


def ensure_kopub() -> tuple[str | None, str | None]:
    """KoPub World 바탕을 확보한다. 캐시에 있으면 그대로, 없으면 공식에서 자동 다운로드.
    다운로드·사용 자체를 라이선스 동의로 간주한다(별도 프롬프트 없음).
    네트워크 실패 시 (None, None) → 호출부가 MuPDF 내장 폰트로 폴백."""
    c = cached()
    if c[0]:
        return c
    print(_LICENSE_NOTICE, file=sys.stderr)
    if _download_official():
        return cached()
    return None, None
