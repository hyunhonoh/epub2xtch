"""epub2xtch — EPUB → XTEink X3/X4 XTC/XTCH 로컬 변환기.

공개 API:
    from epub2xtch import epub_to_xtc
    epub_to_xtc("book.epub", "book.xtc", device="x3", bit_depth=2)
"""
from __future__ import annotations

from .core import (
    DEFAULT_FONTSIZE,
    DEFAULT_MARGIN_PCT,
    DEVICES,
    build_xtc,
    default_font,
    epub_to_xtc,
    extract_chapters,
    pack_chapters,
    pack_xtg,
    pack_xth,
    render_epub_pages,
)

__version__ = "0.1.0"

__all__ = [
    "epub_to_xtc", "build_xtc", "render_epub_pages", "extract_chapters",
    "pack_xth", "pack_xtg", "pack_chapters", "default_font",
    "DEVICES", "DEFAULT_FONTSIZE", "DEFAULT_MARGIN_PCT", "__version__",
]
