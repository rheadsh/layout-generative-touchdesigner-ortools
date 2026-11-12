"""Prueba el solver fuera de TD y genera previews SVG de varias semillas."""
import sys
import time

from editorial_solver import Block, Page, solve

COLORS = {"headline": "#111", "image": "#c9c3b8", "text": "#e8e4dc",
          "caption": "#f4d35e", "quote": "#ee6c4d"}

BLOCKS = [
    Block("titular", "headline", min_w=6, max_h=3, min_h=2, priority=5, rel=["top"],
          text="La ciudad que se reinventa"),
    Block("foto1", "image", min_w=4, min_h=4, priority=4, aspect=1.5),
    Block("pie1", "caption", min_h=1, max_h=1, priority=1, rel=["below:foto1"],
          text="Vista aérea del centro"),
    Block("cuerpo1", "text", min_w=3, max_w=6, priority=2, chars=1800),
    Block("cita", "quote", min_w=3, max_w=6, min_h=2, max_h=3, priority=3, required=False,
          text="«Diseñar es decidir»"),
    Block("foto2", "image", min_w=3, min_h=3, priority=3, aspect=0.8, required=False),
    Block("cuerpo2", "text", min_w=3, max_w=6, priority=2, chars=1500),
]


def to_svg(res, page, path):
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{page.width/3}" '
             f'height="{page.height/3}" viewBox="0 0 {page.width} {page.height}">',
             f'<rect width="{page.width}" height="{page.height}" fill="#fff" stroke="#000"/>']
    for b in res["blocks"]:
        fill = COLORS.get(b["kind"], "#ccc")
        tc = "#fff" if b["kind"] == "headline" else "#000"
        parts.append(f'<rect x="{b["x"]:.1f}" y="{b["y"]:.1f}" width="{b["w"]:.1f}" '
                     f'height="{b["h"]:.1f}" fill="{fill}"/>')
        parts.append(f'<text x="{b["x"]+10:.1f}" y="{b["y"]+40:.1f}" font-size="32" '
                     f'font-family="sans-serif" fill="{tc}">{b["id"]}</text>')
    parts.append("</svg>")
    open(path, "w").write("\n".join(parts))


if __name__ == "__main__":
    page = Page()
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    for seed in range(4):
        t = time.time()
        res = solve(BLOCKS, page, seed=seed, time_limit=1.5)
        dt = time.time() - t
        print(f"seed={seed} status={res['status']} obj={res['objective']} "
              f"t={dt:.2f}s blocks={[b['id'] for b in res['blocks']]}")
        # Comprobación independiente de solapes y límites.
        bs = res["blocks"]
        for b in bs:
            assert b["col"] + b["cols"] <= page.cols and b["row"] + b["rows"] <= page.rows
        for i in range(len(bs)):
            for j in range(i + 1, len(bs)):
                a, c = bs[i], bs[j]
                overlap = (a["col"] < c["col"] + c["cols"] and c["col"] < a["col"] + a["cols"] and
                           a["row"] < c["row"] + c["rows"] and c["row"] < a["row"] + a["rows"])
                assert not overlap, (a["id"], c["id"])
                # bs conserva el orden de entrada → orden de lectura en raster.
                assert a["row"] * page.cols + a["col"] <= c["row"] * page.cols + c["col"], \
                    ("orden", a["id"], c["id"])
        to_svg(res, page, f"{out_dir}/layout_seed{seed}.svg")
