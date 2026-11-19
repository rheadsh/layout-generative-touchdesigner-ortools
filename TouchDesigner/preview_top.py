# Script TOP "preview": dibuja layout_out como rectángulos de color (debug rápido).
# Para la pieza final usa Text TOP / Text COMP con un Replicator sobre layout_out.
import numpy as np

COLORS = {
    'headline': (0.07, 0.07, 0.07),
    'image':    (0.79, 0.76, 0.72),
    'text':     (0.91, 0.89, 0.86),
    'caption':  (0.96, 0.83, 0.37),
    'quote':    (0.93, 0.42, 0.30),
}


def onSetupParameters(scriptOp):
    return


def onCook(scriptOp):
    comp = scriptOp.parent()
    W, H = int(comp.par.Pagew), int(comp.par.Pageh)
    img = np.ones((H, W, 4), dtype=np.float32)
    t = comp.op('layout_out')
    if t is not None and t.numRows > 1:
        for r in range(1, t.numRows):
            x, y = int(float(t[r, 'x'])), int(float(t[r, 'y']))
            w, h = int(float(t[r, 'w'])), int(float(t[r, 'h']))
            c = COLORS.get(t[r, 'kind'].val, (0.6, 0.6, 0.6))
            img[y:y + h, x:x + w, :3] = c
    # TD tiene el origen abajo-izquierda: invertimos filas.
    scriptOp.copyNumpyArray(np.ascontiguousarray(img[::-1]))
