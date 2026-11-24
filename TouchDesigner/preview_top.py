# Script TOP "preview": dibuja layout_out como rectángulos de color (debug rápido).
# Para la pieza final usa Text TOP / Text COMP con un Replicator sobre layout_out.
import numpy as np


def onCook(scriptOp):
    comp = scriptOp.parent()
    cfg_dat = comp.op('layout_config')
    if cfg_dat is None:  # componente anterior: ejecuta update_workflow.py
        return
    cfg = cfg_dat.module
    W, H = int(comp.par.Pagew.eval()), int(comp.par.Pageh.eval())
    img = np.ones((H, W, 4), dtype=np.float32)
    t = comp.op('layout_out')
    if t is not None and t.numRows > 1:
        for r in range(1, t.numRows):
            x0, y0 = int(float(t[r, 'x'])), int(float(t[r, 'y']))
            x1, y1 = x0 + int(float(t[r, 'w'])), y0 + int(float(t[r, 'h']))
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(W, x1), min(H, y1)
            if x1 <= x0 or y1 <= y0:
                continue
            color = cfg.KIND_COLORS.get(t[r, 'kind'].val, cfg.DEFAULT_COLOR)
            img[y0:y1, x0:x1, :3] = cfg.hex_to_rgb(color)
    # TD tiene el origen abajo-izquierda: invertimos filas.
    scriptOp.copyNumpyArray(np.ascontiguousarray(img[::-1]))
