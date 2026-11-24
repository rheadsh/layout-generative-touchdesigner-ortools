"""
Construye el componente 'editorial_solver' en TouchDesigner.

Uso (Textport, Alt+T), con la raíz del proyecto en LAYOUT_GENERATIVE_DIR o con el
.toe guardado en la raíz (o en una subcarpeta) del proyecto:
    exec(open('<raiz>/TouchDesigner/build_network.py', encoding='utf-8').read())

Requiere haber corrido `uv sync` en la raíz del proyecto (crea .venv con Python 3.11).

Al final del archivo, build() se ejecuta salvo que el script se cargue con
__name__ == MODULE_NAME, que es como lo carga update_workflow.py para reutilizar
setup_media(), add_weight_pars() y los callbacks sin reconstruir el componente.
"""

import importlib.util
import os
import re

PARENT = '/project1'
MODULE_NAME = 'layout_build_network'


def resolve_root():
    """Raíz del proyecto: $LAYOUT_GENERATIVE_DIR, o project.folder (o su padre)."""
    env = os.environ.get('LAYOUT_GENERATIVE_DIR')
    if env:
        return env
    folder = project.folder
    for cand in (os.path.dirname(folder), folder):
        if os.path.isfile(os.path.join(cand, 'editorial_solver.py')):
            return cand
    raise RuntimeError(
        'No se encontró editorial_solver.py: define la variable de entorno '
        'LAYOUT_GENERATIVE_DIR o guarda el .toe en la raíz del proyecto.'
    )


def lib_dir(root):
    # site-packages del entorno uv; la Extension lo agrega con sys.path.append
    return os.path.join(root, '.venv', 'lib', 'python3.11', 'site-packages')


def load_config(root):
    """Carga layout_config.py desde disco (sin OR-Tools)."""
    spec = importlib.util.spec_from_file_location(
        'layout_config_disk', os.path.join(root, 'layout_config.py')
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FRAME_EXEC = '''def onFrameStart(frame):
    parent().Poll()
'''

PAR_EXEC = '''LAYOUT_PARS = ('Cols', 'Rows', 'Pagew', 'Pageh', 'Margin', 'Gutter', 'Rowpadding',
               'Charspermodule', 'Seed', 'Timelimit', 'Workers',
               'Wcoverage', 'Warea', 'Waspect', 'Woptional', 'Wcolumn', 'Deterministic')

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


MEDIA_CALLBACKS = """def onReplicate(comp, allOps, newOps, template, master):
    for node in allOps:
        for r in range(1, template.numRows):
            if template[r, 'name'].val == node.name:
                node.store('layout_block_id', template[r, 'id'].val)
                node.store('layout_active', True)
                node.comment = 'Content for block: ' + template[r, 'id'].val
                break
    return

def onRemoveReplicant(comp, replicant):
    # Conserva la réplica (y su archivo asignado) cuando el bloque sale de la
    # solución. El cuerpo NO puede quedar vacío: TouchDesigner trata una función
    # que solo hace `return` como no definida y destruye la réplica.
    replicant.store('layout_active', False)
    return
"""

# Mantener en sincronía con editorial_solver.Weights (lo comprueba tests/test_td_scripts.py).
WEIGHT_PARS = (
    ('Wcoverage', 'Peso cobertura', 2),
    ('Warea', 'Peso área', 4),
    ('Waspect', 'Peso proporción', 3),
    ('Woptional', 'Peso opcionales', 6),
    ('Wcolumn', 'Peso columna (seed)', 2),
)


def add_weight_pars(comp, page):
    """Añade los pesos y Deterministic a la página 'Solver' si faltan."""
    for name, label, val in WEIGHT_PARS:
        if not hasattr(comp.par, name):
            p = page.appendInt(name, label=label)[0]
            p.default = p.val = val
            p.normMin, p.normMax = 0, 20
            p.min, p.max = 0, 20
            p.clampMin = p.clampMax = True
    if not hasattr(comp.par, 'Deterministic'):
        page.appendToggle('Deterministic', label='Determinista')[0].val = False


# DATs sincronizados con archivos del repositorio: nombre -> ruta relativa a la raíz.
SOURCE_FILES = {
    'editorial_solver': 'editorial_solver.py',
    'layout_config': 'layout_config.py',
    'EditorialSolverExt': 'TouchDesigner/EditorialSolverExt.py',
    'preview_callbacks': 'TouchDesigner/preview_top.py',
}


def link_source_files(comp, root):
    """Crea (si falta) y vincula cada DAT de SOURCE_FILES con su archivo en disco."""
    for name, rel in SOURCE_FILES.items():
        dat = comp.op(name)
        if dat is None:
            dat = comp.create(textDAT, name)
        dat.par.file = os.path.join(root, rel)
        dat.par.syncfile = True


def remove_default_callbacks(comp):
    """Borra los DATs de callbacks que TD crea al crear un Script TOP o un
    Replicator COMP (p. ej. preview_callbacks1) y que nadie referencia."""
    used = set()
    for owner in (comp, comp.op('media_inputs')):
        if owner is None:
            continue
        for node in owner.children:
            par = getattr(node.par, 'callbacks', None)
            target = par.eval() if par is not None else None
            if target is not None:
                used.add(target.path if hasattr(target, 'path') else str(target))
    for owner in (comp, comp.op('media_inputs')):
        if owner is None:
            continue
        for node in list(owner.children):
            if node.isDAT and re.fullmatch(r'\w*callbacks\d+', node.name) and node.path not in used:
                node.destroy()


def setup_media(comp):
    """Crea (si falta) la infraestructura de medios: media_inputs, replicator, media_map."""
    media = comp.op('media_inputs')
    if media is None:
        media = comp.create(baseCOMP, 'media_inputs')
        media.nodeX, media.nodeY = 1000, -400
    table = media.op('replicate_table')
    if table is None:
        table = media.create(tableDAT, 'replicate_table')
        table.nodeX, table.nodeY = 0, 200
    master = media.op('movie_master')
    if master is None:
        master = media.create(moviefileinTOP, 'movie_master')
        master.par.file = ''
        master.nodeX, master.nodeY = -250, 0
    callbacks = media.op('replicator_callbacks')
    if callbacks is None:
        callbacks = media.create(textDAT, 'replicator_callbacks')
    if callbacks.text != MEDIA_CALLBACKS:
        callbacks.text = MEDIA_CALLBACKS
    replicator = media.op('replicator')
    if replicator is None:
        replicator = media.create(replicatorCOMP, 'replicator')
    replicator.par.master = master.path
    replicator.par.destination = media.path
    replicator.par.callbacks = callbacks.path
    replicator.par.ignorefirstrow = True
    replicator.par.namefromtable = 'colbyname'
    replicator.par.colname = 'name'
    replicator.par.opprefix = ''
    replicator.par.template = table.path
    replicator.nodeX, replicator.nodeY = 0, 0
    mapping = comp.op('media_map')
    if mapping is None:
        mapping = comp.create(tableDAT, 'media_map')
        mapping.nodeX, mapping.nodeY = 1000, -200
    return media


def build():
    project_dir = resolve_root()
    cfg = load_config(project_dir)
    root = op(PARENT)
    old = root.op('editorial_solver')
    if old is not None:
        old.destroy()
    comp = root.create(baseCOMP, 'editorial_solver')

    # Parámetros custom
    pg = comp.appendCustomPage('Solver')

    def add_par(append, name, label, val, lo, hi):
        p = append(name, label=label)[0]
        p.default = p.val = val
        p.normMin, p.normMax = lo, hi

    def addInt(*args):
        add_par(pg.appendInt, *args)

    def addFloat(*args):
        add_par(pg.appendFloat, *args)

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
    add_weight_pars(comp, pg)
    pg.appendFolder('Libpath', label='Ruta librerías')[0].val = lib_dir(project_dir)
    st = pg.appendStr('Status', label='Estado')[0]
    st.readOnly = True

    # Módulo solver (sincronizado con el .py en disco)
    link_source_files(comp, project_dir)

    # Tablas
    tin = comp.create(tableDAT, 'blocks_in')
    tin.clear()
    for row in cfg.sample_table():
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
    pv = comp.create(scriptTOP, 'preview')
    pv.par.callbacks = 'preview_callbacks'
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
8. Wcoverage/Warea/Waspect/Woptional/Wcolumn weight the objective (0-20);
   Deterministic makes the same Seed give the same layout.
9. To refresh an existing component after editing the .py files, run
   TouchDesigner/update_workflow.py in the Textport (no rebuild).
'''
    help_dat.nodeX, help_dat.nodeY = 0, -400

    # Layout de nodos legible
    for i, o in enumerate(
        [*(comp.op(n) for n in SOURCE_FILES), tin, de, comp.op('layout_out'), pv, fe, pe]
    ):
        o.nodeX, o.nodeY = (i % 5) * 200, -(i // 5) * 200

    # Extension promocionada → comp.Solve(), comp.Poll()
    comp.par.ext0object = "op('./EditorialSolverExt').module.EditorialSolverExt(me)"
    comp.par.ext0promote = True
    comp.initializeExtensions()

    setup_media(comp)
    remove_default_callbacks(comp)
    comp.Solve()
    print('editorial_solver listo en', comp.path)
    return comp


if __name__ != MODULE_NAME:
    build()
