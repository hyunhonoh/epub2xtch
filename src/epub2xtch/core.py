"""EPUB → XTC/XTCH 변환 코어 (macOS 네이티브, Calibre 불필요).

XTEink X3/X4 전자잉크 리더기의 네이티브 포맷(XTC 1비트 / XTCH 2비트)으로 변환한다.

렌더링 파이프라인:
  PyMuPDF가 EPUB을 화면 크기로 리플로우·페이지네이션 → 페이지별 그레이 이미지 →
  1/2비트로 양자화 → numpy.packbits 로 비트플레인 패킹.

── XTC/XTCH 바이너리 포맷 ────────────────────────────────────────────────
규격은 CrossPoint Reader 커펌(MIT, © 2025 Dave Allie)의 파서 소스(lib/Xtc/)를
참고해 파악한 것이며, 아래 인코더는 그 규격을 바탕으로 독립 구현했다. 전부 little-endian.

  파일 레이아웃:
    헤더(56B) → [메타데이터] → [챕터블록] → 페이지테이블(16B/페이지) → 페이지 데이터
  헤더(56B): magic, ver(1,0), pageCount, readDir, hasMeta/Thumb/Chap, currentPage,
    metadataOffset, pageTableOffset, dataOffset, thumbOffset, chapterOffset.
  메타데이터(있으면): title @0x38(128B, UTF-8 null-term), author @0xB8(64B).
  페이지테이블 엔트리(16B): dataOffset(Q) dataSize(I=블롭 전체 길이) width(H) height(H).
  페이지 블롭 = 22B 헤더(magic,w,h,colorMode=0,compression=0,dataSize,md5=0) + 비트맵.
    - XTC(1비트/XTG): 행 우선, 8px/바이트, MSB first. bit=1 이 흰색.
    - XTCH(2비트/XTH): 열 우선·오른→왼(저장 열 = w-1-x), 세로 8px/바이트(위 픽셀=MSB),
      plane1(상위비트) 전체 + plane2(하위비트) 전체 연속. 값 = (bit1<<1)|bit2 (0~3).
      planeSize = w*ceil(h/8), dataSize = planeSize*2.
  챕터블록: 96B/엔트리 = 이름[80](UTF-8) + startPage(H) + endPage(H) + 패딩[12]. 1-based.
    커펌이 챕터 수를 (pageTableOffset-chapterOffset)/96 으로 계산하므로 페이지테이블 바로 앞에 둔다.
  매직: 파일 XTC=0x00435458 / XTCH=0x48435458, 페이지 XTG=0x00475458 / XTH=0x00485458.

── 기기 참고 ─────────────────────────────────────────────────────────────
  X3=528×792(3.7", 자이로 틸트 페이지넘김), X4=480×800(4.3"). 둘 다 읽기전용(앱 설치 불가).
  CrossPoint 커펌(crosspoint.kr)을 깔면 EPUB을 직접 읽어 XTC가 필수는 아니다.
  순정 펌웨어이거나 더 빠른 렌더·작은 용량을 원할 때 XTC가 유용하다.
"""
from __future__ import annotations

import struct
from pathlib import Path

import os

import pymupdf
from PIL import Image

try:
    import numpy as np
except ImportError:  # numpy 없으면 순수 파이썬 폴백 사용
    np = None

# ── 매직넘버 (little-endian) ──────────────────────────────────────────────
XTC_MAGIC = 0x00435458   # "XTC\0"  파일 헤더 (1비트)
XTCH_MAGIC = 0x48435458  # "XTCH"   파일 헤더 (2비트)
XTG_MAGIC = 0x00475458   # "XTG\0"  페이지 데이터 (1비트)
XTH_MAGIC = 0x00485458   # "XTH\0"  페이지 데이터 (2비트)

# ── 기기별 화면 해상도 (width, height) ────────────────────────────────────
DEVICES = {
    "x3": (528, 792),   # 3.7"
    "x4": (480, 800),   # 4.3"
}

DEFAULT_FONTSIZE = 22
DEFAULT_MARGIN_PCT = 2.5  # 실제 남는 좌우 여백(%). 0=끝까지 꽉. overscan+crop로 맞춘다

HEADER_SIZE = 56
PAGE_TABLE_ENTRY_SIZE = 16
PAGE_HEADER_SIZE = 22
META_TITLE_OFF = 0x38
META_AUTHOR_OFF = 0xB8
META_END = 0xF8  # 0xB8 + 64
CHAPTER_ENTRY_SIZE = 96


def default_font() -> tuple[str | None, str | None]:
    """기본 렌더 폰트. 환경변수 EPUB2XTCH_FONT / EPUB2XTCH_FONT_BOLD 로 지정 가능.
    지정이 없으면 (None, None) → MuPDF 내장 폰트로 렌더한다.
    (폰트를 패키지에 번들·재배포하지 않는다. KoPub 등은 공식에서 받아 --font 로 지정.)"""
    reg = os.environ.get("EPUB2XTCH_FONT") or None
    bold = os.environ.get("EPUB2XTCH_FONT_BOLD") or None
    return reg, bold


# ── 렌더링: EPUB → 페이지별 8bit 그레이 이미지 ─────────────────────────────
def _render_doc(doc, width: int, height: int, margin: int = 0) -> list[Image.Image]:
    # 콘텐츠는 (width-2m)x(height-2m)로 레이아웃되어 있고, 흰 캔버스 중앙(오프셋 m)에 붙여
    # 책 CSS와 무관하게 정확히 균일한 여백 m 을 만든다.
    cw, ch = width - 2 * margin, height - 2 * margin
    pages: list[Image.Image] = []
    for page in doc:
        pix = page.get_pixmap(colorspace=pymupdf.csGRAY, alpha=False)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        canvas = Image.new("L", (width, height), 255)
        img = img.crop((0, 0, min(cw, img.width), min(ch, img.height)))
        canvas.paste(img, (margin, margin))
        pages.append(canvas)
    return pages


# 여백 축소용 CSS: 책 자체 CSS의 바깥 여백/패딩을 0으로 눌러 화면을 꽉 채운다.
_TRIM_CSS = ("html,body{margin:0 !important;padding:0 !important}"
             "div,section,p,blockquote,li{margin-left:0 !important;margin-right:0 !important;"
             "padding-left:0 !important;padding-right:0 !important}")


def _quiet_mupdf():
    """깨진 책 CSS 등에서 나오는 MuPDF 경고 스팸을 끈다."""
    try:
        pymupdf.TOOLS.mupdf_display_errors(False)
    except Exception:
        pass


def _apply_user_css(font: str | None, font_bold: str | None, trim_margins: bool = False,
                    line_spacing: float | None = None):
    """렌더 폰트/여백/줄간격을 사용자 CSS로 강제. 최종 그림에 반영되므로 기기 내장폰트와 무관."""
    mu = pymupdf.mupdf
    parts = []
    if font:
        reg = Path(font).resolve()
        parts.append(f'@font-face{{font-family:"UF";src:url("{reg}")}}')
        if font_bold:
            bold = Path(font_bold).resolve()
            parts.append(f'@font-face{{font-family:"UF";font-weight:bold;src:url("{bold}")}}')
        parts.append('*{font-family:"UF" !important}')
    if trim_margins:
        parts.append(_TRIM_CSS)
    if line_spacing:
        parts.append(f'*{{line-height:{line_spacing} !important}}')
    mu.fz_set_user_css("".join(parts))
    if parts:
        try:
            mu.fz_set_use_document_css(1)
        except Exception:
            pass


def _open_laid_out(epub_path: str, width: int, height: int, fontsize: int,
                   font: str | None = None, font_bold: str | None = None,
                   trim_margins: bool = False, margin: int = 0,
                   line_spacing: float | None = None):
    _quiet_mupdf()
    _apply_user_css(font, font_bold, trim_margins, line_spacing)
    doc = pymupdf.open(epub_path)
    try:
        doc.layout(width=width - 2 * margin, height=height - 2 * margin, fontsize=fontsize)
    except Exception:
        pass
    return doc


def render_epub_pages(epub_path: str, width: int, height: int, fontsize: int = DEFAULT_FONTSIZE,
                      font: str | None = None, font_bold: str | None = None,
                      trim_margins: bool = True, margin: int = 0) -> list[Image.Image]:
    doc = _open_laid_out(epub_path, width, height, fontsize, font, font_bold, trim_margins, margin)
    pages = _render_doc(doc, width, height, margin)
    doc.close()
    return pages


def _measure_margins(doc, height: int) -> tuple[int, int, int] | None:
    """리플로우 페이지들에서 본문 먹(검정)이 실제로 시작/끝나는 구조적 여백을 실측.
    반환: (좌, 상, 하) px. overscan 양을 정하는 데 쓴다. numpy 없으면 None.
    좌·상은 표본 중앙값(표지/이미지 페이지에 둔감), 하는 '가장 꽉 찬 페이지' 기준(min 여백)."""
    if np is None:
        return None
    n = len(doc)
    if n == 0:
        return (0, 0, 0)
    fracs = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
    idxs = sorted({min(n - 1, max(0, int(n * f))) for f in fracs})
    lefts: list[int] = []
    tops: list[int] = []
    botgaps: list[int] = []
    for i in idxs:
        pix = doc[i].get_pixmap(colorspace=pymupdf.csGRAY, alpha=False)
        a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
        dark = a < 128
        cols = dark.any(axis=0)
        rows = dark.any(axis=1)
        if cols.any():
            lefts.append(int(cols.argmax()))
        if rows.any():
            tops.append(int(rows.argmax()))
            botgaps.append(int(height - 1 - int(rows[::-1].argmax())))
    if not lefts:
        return (0, 0, 0)
    left = int(np.median(lefts))
    top = int(np.median(tops)) if tops else 0
    bottom = min(botgaps) if botgaps else 0   # 꽉 찬 페이지의 하단 여백 = 구조적 하단 여백
    return (left, top, bottom)


def _render_fill(epub_path: str, w: int, h: int, fontsize: int,
                 font: str | None, font_bold: str | None, target_m: int,
                 line_spacing: float | None = None):
    """상하좌우 네 면을 target 여백만 남기고 꽉 채워 렌더.
    MuPDF 구조적 여백(좌·상·하)을 실측해 그만큼 더 넓고/높게 레이아웃(overscan)한 뒤
    가장자리를 잘라내 실제 여백을 목표치로 맞춘다. 마지막 줄은 잘리지 않는다.
    반환: (열린 doc, 페이지 이미지 리스트). doc은 목차 추출용이라 호출측에서 닫는다."""
    target_v = round(target_m * h / w)   # 세로 목표 여백(같은 %)
    # 1) 화면 크기 기준으로 구조적 여백 실측
    probe = _open_laid_out(epub_path, w, h, fontsize, font, font_bold, True, 0, line_spacing)
    m = _measure_margins(probe, h)
    probe.close()
    if m is None:  # numpy 폴백: 기존 캔버스-패딩 방식
        doc = _open_laid_out(epub_path, w, h, fontsize, font, font_bold, True, target_m, line_spacing)
        return doc, _render_doc(doc, w, h, target_m)
    rl, rt, rb = m
    ox = max(0, rl - target_m)                      # 좌우 각각 넘길 양
    oyt = max(0, rt - target_v)                      # 상단 넘길 양
    oyb = max(0, rb - target_v)                      # 하단 넘길 양
    lw = w + 2 * ox                                  # overscan 폭
    lh = h + oyt + oyb                               # overscan 높이
    doc = _open_laid_out(epub_path, lw, lh, fontsize, font, font_bold, True, 0, line_spacing)
    # overscan 후 좌여백 재측정 → 좌 crop 보정(상·하는 구조값 그대로 사용)
    m2 = _measure_margins(doc, lh)
    cx = max(0, ((m2[0] if m2 else rl)) - target_m)
    cy = oyt
    pages: list[Image.Image] = []
    for page in doc:
        pix = page.get_pixmap(colorspace=pymupdf.csGRAY, alpha=False)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        canvas = Image.new("L", (w, h), 255)
        box = img.crop((cx, cy, min(cx + w, img.width), min(cy + h, img.height)))
        canvas.paste(box, (0, 0))
        pages.append(canvas)
    return doc, pages


def extract_chapters(doc, page_count: int) -> list[tuple[str, int, int]]:
    """EPUB 목차 → [(이름, startPage, endPage)] (1-based). 리플로우 후 페이지에 매핑."""
    try:
        toc = doc.get_toc(simple=True)
    except Exception:
        return []
    entries = [(t.strip() or f"p{pg}", pg) for _lvl, t, pg in toc if isinstance(pg, int) and 1 <= pg <= page_count]
    entries.sort(key=lambda e: e[1])
    out: list[tuple[str, int, int]] = []
    for i, (name, pg) in enumerate(entries):
        end = entries[i + 1][1] - 1 if i + 1 < len(entries) else page_count
        out.append((name, pg, max(pg, end)))
    return out


# ── 양자화 + 비트팩킹 ─────────────────────────────────────────────────────
def _quantize(px_value: int, depth: int, invert: bool) -> int:
    levels = (1 << depth) - 1
    v = (px_value * levels + 127) // 255
    return (levels - v) if invert else v


def _quantize_arr(arr, depth: int, invert: bool):
    levels = (1 << depth) - 1
    v = (arr.astype(np.uint16) * levels + 127) // 255
    if invert:
        v = levels - v
    return v.astype(np.uint8)


def pack_xth(img: Image.Image, w: int, h: int, invert: bool = False) -> bytes:
    """2비트(XTH): plane1(상위)+plane2(하위), 열 우선·오른→왼, 세로 MSB 우선."""
    if np is None:
        return _pack_xth_py(img, w, h, invert)
    arr = np.asarray(img, dtype=np.uint8)
    v = _quantize_arr(arr, 2, invert)
    b1 = (v >> 1) & 1
    b2 = v & 1

    def plane(bits):
        t = bits[:, ::-1].T
        return np.packbits(t, axis=1, bitorder="big").tobytes()
    return plane(b1) + plane(b2)


def pack_xtg(img: Image.Image, w: int, h: int, invert: bool = False) -> bytes:
    """1비트(XTG): 행 우선, 8픽셀/바이트, MSB first. bit=1 이 흰색."""
    if np is None:
        return _pack_xtg_py(img, w, h, invert)
    arr = np.asarray(img, dtype=np.uint8)
    v = _quantize_arr(arr, 1, invert)
    return np.packbits(v, axis=1, bitorder="big").tobytes()


def _pack_xth_py(img: Image.Image, w: int, h: int, invert: bool = False) -> bytes:
    column_bytes = (h + 7) // 8
    plane_size = w * column_bytes
    p1 = bytearray(plane_size)
    p2 = bytearray(plane_size)
    px = img.load()
    for x in range(w):
        col = (w - 1 - x) * column_bytes
        for y in range(h):
            v = _quantize(px[x, y], 2, invert)
            off = col + (y >> 3)
            sh = 7 - (y & 7)
            if v & 0b10:
                p1[off] |= (1 << sh)
            if v & 0b01:
                p2[off] |= (1 << sh)
    return bytes(p1) + bytes(p2)


def _pack_xtg_py(img: Image.Image, w: int, h: int, invert: bool = False) -> bytes:
    row_bytes = (w + 7) // 8
    out = bytearray(row_bytes * h)
    px = img.load()
    for y in range(h):
        base = y * row_bytes
        for x in range(w):
            v = _quantize(px[x, y], 1, invert)
            if v:
                out[base + (x >> 3)] |= (0x80 >> (x & 7))
    return bytes(out)


# ── 페이지 블롭 (22B 헤더 + 비트맵) ───────────────────────────────────────
def _page_blob(bitmap: bytes, w: int, h: int, page_magic: int) -> bytes:
    header = struct.pack("<IHHBBIQ", page_magic, w, h, 0, 0, len(bitmap), 0)
    return header + bitmap


def _truncate_utf8(s: str, max_bytes: int) -> bytes:
    b = s.encode("utf-8")
    if len(b) <= max_bytes:
        return b
    b = b[:max_bytes]
    while b and (b[-1] & 0xC0) == 0x80:
        b = b[:-1]
    if b and (b[-1] & 0x80):
        b = b[:-1]
    return b


def pack_chapters(chapters: list[tuple[str, int, int]]) -> bytes:
    """챕터 블록: 96B/엔트리 = 이름[80] + startPage(H) + endPage(H) + 패딩[12]. 1-based."""
    out = bytearray()
    for name, start, end in chapters:
        name80 = _truncate_utf8(name, 80)
        out += struct.pack("<80sHH12x", name80, start & 0xFFFF, end & 0xFFFF)
    return bytes(out)


def _meta_block(title: str, author: str) -> bytes:
    buf = bytearray(META_END - META_TITLE_OFF)
    tb = title.encode("utf-8")[:127]
    ab = author.encode("utf-8")[:63]
    buf[0:len(tb)] = tb
    off_author = META_AUTHOR_OFF - META_TITLE_OFF
    buf[off_author:off_author + len(ab)] = ab
    return bytes(buf)


# ── 전체 파일 조립 ────────────────────────────────────────────────────────
def build_xtc(pages: list[Image.Image], *, bit_depth: int = 2,
              title: str = "", author: str = "", invert: bool = False,
              chapters: list[tuple[str, int, int]] | None = None) -> bytes:
    if not pages:
        raise ValueError("페이지가 없습니다.")
    if bit_depth == 2:
        file_magic, page_magic, packer = XTCH_MAGIC, XTH_MAGIC, pack_xth
    elif bit_depth == 1:
        file_magic, page_magic, packer = XTC_MAGIC, XTG_MAGIC, pack_xtg
    else:
        raise ValueError("bit_depth 는 1 또는 2")

    chapters = chapters or []
    has_meta = bool(title or author)
    has_chap = bool(chapters)
    meta_off = META_TITLE_OFF if has_meta else 0
    after_meta = META_END if has_meta else HEADER_SIZE
    chap_block = pack_chapters(chapters)
    chap_off = after_meta if has_chap else 0
    page_table_off = after_meta + len(chap_block)
    data_off = page_table_off + len(pages) * PAGE_TABLE_ENTRY_SIZE

    blobs: list[bytes] = []
    table = bytearray()
    cursor = data_off
    for img in pages:
        w, h = img.size
        blob = _page_blob(packer(img, w, h, invert), w, h, page_magic)
        table += struct.pack("<QIHH", cursor, len(blob), w, h)
        blobs.append(blob)
        cursor += len(blob)

    header = struct.pack(
        "<IBBHBBBBIQQQQQ",
        file_magic, 1, 0, len(pages), 0,
        1 if has_meta else 0, 0, 1 if has_chap else 0, 1,
        meta_off, page_table_off, data_off, 0, chap_off,
    )
    assert len(header) == HEADER_SIZE, len(header)

    out = bytearray()
    out += header
    if has_meta:
        out += _meta_block(title, author)
    if has_chap:
        out += chap_block
    out += table
    for b in blobs:
        out += b
    return bytes(out)


def epub_to_xtc(epub_path: str, out_path: str, *, device: str = "x3",
                bit_depth: int = 2, fontsize: int = DEFAULT_FONTSIZE, invert: bool = False,
                title: str = "", author: str = "", toc: bool = True,
                font: str | None = None, font_bold: str | None = None,
                trim_margins: bool = True, margin_pct: float = DEFAULT_MARGIN_PCT,
                line_spacing: float | None = None) -> int:
    if device not in DEVICES:
        raise ValueError(f"알 수 없는 기기: {device} (선택: {', '.join(DEVICES)})")
    # font=None → 기본 KoPub 바탕 자동. font="" → MuPDF 기본. font=경로 → 그 폰트.
    if font is None:
        font, font_bold = default_font()
    w, h = DEVICES[device]
    if trim_margins:
        # 좌우를 margin_pct 여백만 남기고 꽉 채움(overscan+crop)
        target_m = round(w * margin_pct / 100)
        doc, pages = _render_fill(epub_path, w, h, fontsize, font, font_bold, target_m, line_spacing)
    else:
        # 책 원본 여백 유지
        doc = _open_laid_out(epub_path, w, h, fontsize, font, font_bold, False, 0, line_spacing)
        pages = _render_doc(doc, w, h, 0)
    chapters = extract_chapters(doc, len(pages)) if toc else []
    doc.close()
    if not title:
        title = Path(epub_path).stem
    data = build_xtc(pages, bit_depth=bit_depth, title=title, author=author,
                     invert=invert, chapters=chapters)
    Path(out_path).write_bytes(data)
    return len(pages)
