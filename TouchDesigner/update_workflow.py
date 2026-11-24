"""Run in TD Textport with UTF-8; refreshes the existing component without rebuilding.

exec(open('<raiz>/TouchDesigner/update_workflow.py', encoding='utf-8').read())
"""

import os
from types import SimpleNamespace

_COMP = '/project1/editorial_solver'


def _resolve_root():
    env = os.environ.get('LAYOUT_GENERATIVE_DIR')
    if env:
        return env
    for cand in (os.path.dirname(project.folder), project.folder):
        if os.path.isfile(os.path.join(cand, 'editorial_solver.py')):
            return cand
    raise RuntimeError(
        'No se encontró editorial_solver.py: define LAYOUT_GENERATIVE_DIR '
        'o guarda el .toe en la raíz del proyecto.'
    )


def _load_build_module(root):
    """Ejecuta build_network.py con los globales del Textport (operadores de TD
    incluidos) y __name__ = MODULE_NAME, para que no llame a build()."""
    path = os.path.join(root, 'TouchDesigner', 'build_network.py')
    namespace = {**globals(), '__name__': 'layout_build_network'}
    with open(path, encoding='utf-8-sig') as f:
        exec(compile(f.read(), path, 'exec'), namespace)
    return SimpleNamespace(**namespace)


root_dir = _resolve_root()
bn = _load_build_module(root_dir)
c = op(_COMP)

if not hasattr(c.par, 'Blockcount'):
    c.appendCustomPage('Solver').appendInt('Blockcount', label='Número de bloques')[0].val = max(
        1, c.op('blocks_in').numRows - 1
    )
solver_page = next(page for page in c.customPages if page.name == 'Solver')
c.par.Blockcount.page = solver_page
for page in list(c.customPages):
    if page.name == 'Pieza' and not page.pars:
        page.destroy()
c.par.Blockcount.normMin = 1
c.par.Blockcount.normMax = 100
c.par.Blockcount.min = 1
c.par.Blockcount.clampMin = True
bn.add_weight_pars(c, solver_page)

bn.link_source_files(c, root_dir)
c.op('par_exec').text = bn.PAR_EXEC
bn.setup_media(c)
bn.remove_default_callbacks(c)
c.initializeExtensions()
c.Solve()
