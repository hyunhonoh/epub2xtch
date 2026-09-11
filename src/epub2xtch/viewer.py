"""XTC/XTCH 뷰어 — 기기 없이 맥에서 변환 결과를 확인한다.

커펌(crosspoint-reader)의 xthPixelValue / 페이지 포맷을 그대로 디코드하므로,
표시 픽셀은 실기기 출력과 동일하다(e-ink 잔상·상태바 UI 제외).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PIL import Image

XTC_MAGIC = 0x00435458
XTCH_MAGIC = 0x48435458
XTG_MAGIC = 0x00475458
XTH_MAGIC = 0x00485458
HEADER_FMT = "<IBBHBBBBIQQQQQ"
CHAPTER_ENTRY_SIZE = 96


class XtcReader:
    def __init__(self, path: str):
        self.data = Path(path).read_bytes()
        h = struct.unpack_from(HEADER_FMT, self.data, 0)
        (self.magic, self.vmaj, self.vmin, self.page_count, self.read_dir,
         self.has_meta, self.has_thumb, self.has_chap, self.cur_page,
         self.meta_off, self.pt_off, self.data_off, self.thumb_off, self.chap_off) = h
        if self.magic not in (XTC_MAGIC, XTCH_MAGIC):
            raise ValueError(f"XTC 파일이 아닙니다 (magic={self.magic:#010x})")
        self.bit_depth = 2 if self.magic == XTCH_MAGIC else 1

    @property
    def title(self) -> str:
        if not self.has_meta:
            return ""
        return self.data[0x38:0x38 + 128].split(b"\x00")[0].decode("utf-8", "replace")

    @property
    def author(self) -> str:
        if not self.has_meta:
            return ""
        return self.data[0xB8:0xB8 + 64].split(b"\x00")[0].decode("utf-8", "replace")

    def chapters(self) -> list[tuple[str, int, int]]:
        if not self.has_chap or self.chap_off == 0:
            return []
        cnt = (self.pt_off - self.chap_off) // CHAPTER_ENTRY_SIZE
        out = []
        for i in range(cnt):
            b = self.chap_off + i * CHAPTER_ENTRY_SIZE
            name = self.data[b:b + 80].split(b"\x00")[0].decode("utf-8", "replace")
            start = struct.unpack_from("<H", self.data, b + 0x50)[0]
            end = struct.unpack_from("<H", self.data, b + 0x52)[0]
            if not name and start == 0 and end == 0:
                break
            out.append((name, start, end))
        return out

    def _page_entry(self, idx: int):
        return struct.unpack_from("<QIHH", self.data, self.pt_off + idx * 16)

    def decode_page(self, idx: int, invert: bool = False) -> Image.Image:
        if not (0 <= idx < self.page_count):
            raise IndexError(idx)
        o, size, w, h = self._page_entry(idx)
        pm = struct.unpack_from("<I", self.data, o)[0]
        bmp = o + 22
        img = Image.new("L", (w, h))
        px = img.load()
        if pm == XTH_MAGIC:  # 2비트
            cb = (h + 7) // 8
            ps = w * cb
            p1 = self.data[bmp:bmp + ps]
            p2 = self.data[bmp + ps:bmp + 2 * ps]
            lut = [0, 85, 170, 255]
            for x in range(w):
                col = (w - 1 - x) * cb
                for y in range(h):
                    off = col + (y >> 3)
                    sh = 7 - (y & 7)
                    v = (((p1[off] >> sh) & 1) << 1) | ((p2[off] >> sh) & 1)
                    px[x, y] = lut[v]
        elif pm == XTG_MAGIC:  # 1비트: bit=1 흰색
            rb = (w + 7) // 8
            for y in range(h):
                base = bmp + y * rb
                for x in range(w):
                    bit = (self.data[base + (x >> 3)] >> (7 - (x & 7))) & 1
                    px[x, y] = 255 if bit else 0
        else:
            raise ValueError(f"알 수 없는 페이지 매직 {pm:#010x}")
        if invert:
            img = Image.eval(img, lambda v: 255 - v)
        return img


def _scaled(img: Image.Image, scale: int) -> Image.Image:
    if scale <= 1:
        return img
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST)


def _print_info(r: XtcReader):
    fmt = "XTCH(2비트)" if r.bit_depth == 2 else "XTC(1비트)"
    _o, _size, w, h = r._page_entry(0)
    print(f"포맷: {fmt}  버전 {r.vmaj}.{r.vmin}")
    print(f"제목: {r.title or '-'}   저자: {r.author or '-'}")
    print(f"페이지: {r.page_count}장   해상도: {w}x{h}")
    ch = r.chapters()
    if ch:
        print(f"목차: {len(ch)}개")
        for name, s, e in ch:
            print(f"  p{s:>4}~{e:<4} {name}")
    else:
        print("목차: 없음")


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="xtc-view", description="XTC/XTCH 뷰어 (맥 미리보기)")
    ap.add_argument("input", help="입력 .xtc")
    ap.add_argument("--page", type=int, help="특정 페이지(1-based)만 PNG로")
    ap.add_argument("--range", help="구간 PDF (예: 10-20)")
    ap.add_argument("-o", "--output", help="출력 경로")
    ap.add_argument("--scale", type=int, default=1, help="화면용 확대 배수(NEAREST)")
    ap.add_argument("--invert-preview", action="store_true", help="명암 반전해서 미리보기")
    ap.add_argument("--no-open", action="store_true", help="생성 후 자동으로 열지 않기")
    args = ap.parse_args(argv)

    r = XtcReader(args.input)
    _print_info(r)
    inv = args.invert_preview
    stem = Path(args.input).with_suffix("")

    if args.page is not None:
        out = args.output or f"{stem}.p{args.page}.png"
        _scaled(r.decode_page(args.page - 1, inv), args.scale).save(out)
        print(f"\n→ {out}")
    else:
        if args.range:
            a, b = (int(x) for x in args.range.split("-"))
            idxs = range(a - 1, b)
            out = args.output or f"{stem}.p{a}-{b}.pdf"
        else:
            idxs = range(r.page_count)
            out = args.output or f"{stem}.preview.pdf"
        imgs = [_scaled(r.decode_page(i, inv), args.scale).convert("L") for i in idxs]
        if not imgs:
            print("페이지가 없습니다.")
            return 1
        imgs[0].save(out, "PDF", save_all=True, append_images=imgs[1:], resolution=150)
        print(f"\n→ {out} ({len(imgs)}페이지)")

    if not args.no_open and sys.platform == "darwin":
        import subprocess
        subprocess.run(["open", out], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
