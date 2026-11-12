"""Run in TD Textport with UTF-8; updates in place without rebuilding."""
from pathlib import Path
root_dir = Path('/Users/robertocabezas/Documents/_AI_Ecosystems/claude-code/layout-generative')
c = op('/project1/editorial_solver')
if not hasattr(c.par, 'Blockcount'):
    page = c.appendCustomPage('Solver')
    page.appendInt('Blockcount', label='Número de bloques')[0].val = max(1, c.op('blocks_in').numRows - 1)
solver_page = next(page for page in c.customPages if page.name == 'Solver')
c.par.Blockcount.page = solver_page
for page in list(c.customPages):
    if page.name == 'Pieza' and not page.pars:
        page.destroy()
c.par.Blockcount.normMin = 1
c.par.Blockcount.normMax = 100
c.par.Blockcount.min = 1
c.par.Blockcount.clampMin = True
c.op('EditorialSolverExt').text = (root_dir / 'td/EditorialSolverExt.py').read_text(encoding='utf-8-sig')
# Reuse the constructor's callback definitions, without running build().
source = (root_dir / 'td/build_network.py').read_text(encoding='utf-8-sig')
namespace = {}
exec(source[:source.index('def build():')], namespace)
c.op('par_exec').text = namespace['PAR_EXEC']
c.initializeExtensions()
c.Solve()
