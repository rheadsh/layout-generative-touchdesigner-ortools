"""
Construye el componente 'editorial_solver' en TouchDesigner.

Uso (Textport, Alt+T):
    exec(open('/Users/robertocabezas/Documents/_AI_Ecosystems/claude-code/layout-generative/TouchDesigner/build_network.py', encoding='utf-8').read())

Requiere haber corrido `uv sync` en la raíz del proyecto (crea .venv con Python 3.11).
"""

import os

# --- RUTAS ----------------------------------------------------------------
PROJECT_DIR = '/Users/robertocabezas/Documents/_AI_Ecosystems/claude-code/layout-generative'
TD_DIR = os.path.join(PROJECT_DIR, 'TouchDesigner')
# site-packages del entorno uv; la Extension lo agrega con sys.path.append
LIB_DIR = os.path.join(PROJECT_DIR, '.venv', 'lib', 'python3.11', 'site-packages')
PARENT = '/project1'
# --------------------------------------------------------------------------

SOLVER_PY = os.path.join(PROJECT_DIR, 'editorial_solver.py')

SAMPLE = [
    ['id', 'kind', 'min_w', 'max_w', 'min_h', 'max_h', 'priority', 'aspect', 'chars', 'required', 'rel', 'text'],
    ['titular', 'headline', 6, 0, 2, 3, 5, '', '', 1, 'top', 'La ciudad que se reinventa'],
    ['foto1', 'image', 4, 0, 4, 0, 4, 1.5, '', 1, '', ''],
    ['pie1', 'caption', 1, 0, 1, 1, 1, '', '', 1, 'below:foto1', 'Vista aérea del centro'],
    ['cuerpo1', 'text', 3, 6, 1, 0, 2, '', 1800, 1, '', ''],
    ['cita', 'quote', 3, 6, 2, 3, 3, '', '', 0, '', '«Diseñar es decidir»'],
    ['foto2', 'image', 3, 0, 3, 0, 3, 0.8, '', 0, '', ''],
    ['cuerpo2', 'text', 3, 6, 1, 0, 2, '', 1500, 1, '', ''],
]

FRAME_EXEC = '''def onFrameStart(frame):
    parent().Poll()
'''

PAR_EXEC = '''LAYOUT_PARS = ('Cols', 'Rows', 'Pagew', 'Pageh', 'Margin', 'Gutter', 'Rowpadding',
               'Charspermodule', 'Seed', 'Timelimit', 'Workers')

def onValueChange(par, prev):
    if par.name == 'Blockcount':
        par.owner.Resizeblocks()
    elif par.name in LAYOUT_PARS and par.owner.par.Autosolve:
        par.owner.Solve()

def onPulse(par):
    if par.name == 'Solve':
        par.owner.Solve()
'''

DAT_EXEC = '''def onTableChange(dat, *args):
    if parent().par.Autosolve:
        parent().Solve()
'''


def build():
    root = op(PARENT)
    old = root.op('editorial_solver')
    if old is not None:
        old.destroy()
    comp = root.create(baseCOMP, 'editorial_solver')

    # Parámetros custom
    pg = comp.appendCustomPage('Solver')
    def addInt(name, label, val, lo, hi):
        p = pg.appendInt(name, label=label)[0]
        p.default = p.val = val; p.normMin, p.normMax = lo, hi
    def addFloat(name, label, val, lo, hi):
        p = pg.appendFloat(name, label=label)[0]
        p.default = p.val = val; p.normMin, p.normMax = lo, hi
    pg.appendPulse('Solve', label='Solve')
    pg.appendToggle('Autosolve', label='Auto Solve')[0].val = True
    addInt('Blockcount', 'Número de bloques', 7, 1, 100)
    addInt('Seed', 'Seed (variación)', 0, 0, 100)
    addInt('Cols', 'Columnas', 12, 1, 24)
    addInt('Rows', 'Filas', 16, 1, 32)
    addInt('Pagew', 'Resolución ancho px', 1080, 100, 4000)
    addInt('Pageh', 'Resolución alto px', 1440, 100, 4000)
    addFloat('Margin', 'Margen px', 48, 0, 200)
    addFloat('Gutter', 'Padding columnas px', 12, 0, 200)
    addFloat('Rowpadding', 'Padding filas px', 12, 0, 200)
    addInt('Charspermodule', 'Caracteres por módulo', 60, 10, 400)
    addFloat('Timelimit', 'Tiempo máx (s)', 1.0, 0.05, 10)
    addInt('Workers', 'Hilos CP-SAT', 8, 1, 16)
    pg.appendFolder('Libpath', label='Ruta librerías')[0].val = LIB_DIR
    st = pg.appendStr('Status', label='Estado')[0]
    st.readOnly = True

    # Módulo solver (sincronizado con el .py en disco)
    s = comp.create(textDAT, 'editorial_solver')
    s.par.file = SOLVER_PY
    s.par.syncfile = True

    ext = comp.create(textDAT, 'EditorialSolverExt')
    ext.par.file = os.path.join(TD_DIR, 'EditorialSolverExt.py')
    ext.par.syncfile = True

    # Tablas
    tin = comp.create(tableDAT, 'blocks_in')
    tin.clear()
    for row in SAMPLE:
        tin.appendRow(row)
    comp.create(tableDAT, 'layout_out').clear()

    # Callbacks
    fe = comp.create(executeDAT, 'frame_exec')
    fe.text = FRAME_EXEC
    fe.par.framestart = True
    fe.par.active = True

    pe = comp.create(parameterexecuteDAT, 'par_exec')
    pe.text = PAR_EXEC
    pe.par.op = comp.path
    pe.par.pars = '*'
    pe.par.valuechange = True
    pe.par.onpulse = True

    de = comp.create(datexecuteDAT, 'blocks_exec')
    de.text = DAT_EXEC
    de.par.dat = 'blocks_in'
    de.par.tablechange = True

    # Preview
    cb = comp.create(textDAT, 'preview_callbacks')
    cb.par.file = os.path.join(TD_DIR, 'preview_top.py')
    cb.par.syncfile = True
    pv = comp.create(scriptTOP, 'preview')
    pv.par.callbacks = cb.name
    pv.viewer = True
    output = comp.create(nullTOP, 'OUT_layout')
    output.inputConnectors[0].connect(pv)
    output.viewer = True
    output.display = True
    output.nodeX, output.nodeY = 600, -400
    help_dat = comp.create(textDAT, 'README')
    help_dat.text = '''WORKFLOW / AUTO LAYOUT
1. Edit blocks_in: one row per block.
2. Enable Auto Solve or pulse Solve on the Solver page.
3. Change Seed for a new layout.
4. layout_out contains pixel rectangles and instancing coordinates.
5. OUT_layout shows the color block preview, not final typography/images.
6. The timeline must play so frame_exec can collect worker results.
7. Libpath must point to Python 3.11 site-packages with OR-Tools.
'''
    help_dat.nodeX, help_dat.nodeY = 0, -400

    # Layout de nodos legible
    for i, o in enumerate([s, ext, tin, de, comp.op('layout_out'), cb, pv, fe, pe]):
        o.nodeX, o.nodeY = (i % 5) * 200, -(i // 5) * 200

    # Extension promocionada → comp.Solve(), comp.Poll()
    comp.par.ext0object = "op('./EditorialSolverExt').module.EditorialSolverExt(me)"
    comp.par.ext0promote = True
    comp.initializeExtensions()

    comp.Solve()
    print('editorial_solver listo en', comp.path)
    return comp


build()
