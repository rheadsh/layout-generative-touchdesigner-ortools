"""Genera previews SVG del solver con los bloques de ejemplo (no es una prueba)."""

import argparse
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from editorial_solver import Page, blocks_from_rows, solve
from layout_config import BLOCK_COLUMNS, DEFAULT_COLOR, KIND_COLORS, SAMPLE_ROWS


def sample_blocks():
    return blocks_from_rows(BLOCK_COLUMNS, SAMPLE_ROWS)


def to_svg(res, page, path):
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{page.width / 3:g}" '
        f'height="{page.height / 3:g}" viewBox="0 0 {page.width:g} {page.height:g}">',
        f'<rect width="{page.width:g}" height="{page.height:g}" fill="#fff" stroke="#000"/>',
    ]
    for b in res["blocks"]:
        fill = KIND_COLORS.get(b["kind"], DEFAULT_COLOR)
        tc = "#fff" if b["kind"] == "headline" else "#000"
        parts.append(
            f'<rect x="{b["x"]:.1f}" y="{b["y"]:.1f}" width="{b["w"]:.1f}" '
            f'height="{b["h"]:.1f}" fill="{fill}"/>'
        )
        parts.append(
            f'<text x="{b["x"] + 10:.1f}" y="{b["y"] + 40:.1f}" font-size="32" '
            f'font-family="sans-serif" fill="{tc}">{escape(b["id"])}</text>'
        )
    parts.append("</svg>")
    Path(path).write_text("\n".join(parts), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out_dir", nargs="?", default="previews")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    page, blocks = Page(), sample_blocks()
    for seed in range(4):
        t = time.perf_counter()
        res = solve(blocks, page, seed=seed, time_limit=1.5)
        dt = time.perf_counter() - t
        print(
            f"seed={seed} status={res['status']} obj={res['objective']} "
            f"t={dt:.2f}s blocks={[b['id'] for b in res['blocks']]}"
        )
        to_svg(res, page, out / f"layout_seed{seed}.svg")


if __name__ == "__main__":
    main()
