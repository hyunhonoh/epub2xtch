"""`epub2xtch` 콘솔 명령."""
from __future__ import annotations

from pathlib import Path

from . import fonts
from .core import DEFAULT_FONTSIZE, DEFAULT_MARGIN_PCT, DEVICES, default_font, epub_to_xtc


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="epub2xtch", description="EPUB → XTC/XTCH 변환 (XTEink X3/X4)")
    ap.add_argument("input", help="입력 .epub")
    ap.add_argument("output", nargs="?", help="출력 .xtc (기본: 입력명.xtc)")
    ap.add_argument("-d", "--device", choices=list(DEVICES), default="x3")
    ap.add_argument("-b", "--bits", type=int, choices=(1, 2), default=2, help="색 깊이(기본 2=XTCH)")
    ap.add_argument("-f", "--fontsize", type=int, default=DEFAULT_FONTSIZE,
                    help="본문 폰트 크기(pt, 클수록 글자 큼/페이지 늘어남)")
    ap.add_argument("--invert", action="store_true", help="명암 반전(기기서 반전돼 보이면)")
    ap.add_argument("--no-toc", action="store_true", help="목차(챕터) 넣지 않기")
    ap.add_argument("--font", help="렌더 폰트 TTF/OTF 경로(정체). 지정 시 이 폰트를 그대로 사용")
    ap.add_argument("--font-bold", help="볼드용 폰트 파일(권장: 볼드 유지)")
    ap.add_argument("--no-font", action="store_true", help="MuPDF 내장 폰트로 렌더(KoPub 다운로드 안 함)")
    ap.add_argument("--no-trim", action="store_true", help="여백 정규화 끄기(책 원본 여백 유지)")
    ap.add_argument("--margin", type=float, default=DEFAULT_MARGIN_PCT,
                    help="남는 좌우 여백 %%(기본 2.5, 0=끝까지 꽉 채움). 내부 overscan+crop")
    ap.add_argument("--line-spacing", type=float, default=None,
                    help="줄간격(line-height 배수) 강제. 예 1.6(e-ink 권장). 미지정 시 책 기본")
    ap.add_argument("--author", default="")
    args = ap.parse_args(argv)

    # 폰트 우선순위: --no-font > --font > 환경변수 > (기본) 공식 KoPub 자동 다운로드 > MuPDF 내장(폴백)
    if args.no_font:
        font, font_bold = "", None
    elif args.font:
        font, font_bold = args.font, args.font_bold
    else:
        font, font_bold = default_font()  # 환경변수 EPUB2XTCH_FONT[_BOLD]
        if not font:
            font, font_bold = fonts.ensure_kopub()

    out = args.output or str(Path(args.input).with_suffix(".xtc"))
    n = epub_to_xtc(args.input, out, device=args.device, bit_depth=args.bits,
                    fontsize=args.fontsize, invert=args.invert, author=args.author,
                    toc=not args.no_toc, font=font, font_bold=font_bold,
                    trim_margins=not args.no_trim, margin_pct=args.margin,
                    line_spacing=args.line_spacing)
    size = Path(out).stat().st_size
    print(f"✅ {n}페이지 → {out}  ({size / 1024:.0f} KB, {args.device}, {args.bits}bit)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
