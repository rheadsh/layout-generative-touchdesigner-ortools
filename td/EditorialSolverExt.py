"""
EditorialSolverExt — Extension para un Base COMP en TouchDesigner.

Lee  ./blocks_in   (Table DAT, una fila por bloque)
Escribe ./layout_out (Table DAT, rectángulos resueltos)

El solve corre en un hilo (CP-SAT libera el GIL), así TD no se congela.
El hilo NUNCA toca operadores: deja el resultado en una cola y Poll(),
llamado cada frame por ./frame_exec, lo vuelca a layout_out en el hilo principal.
"""

import hashlib
import re
import queue
import sys
import threading
import time

BLOCK_COLS = ['id', 'kind', 'min_w', 'max_w', 'min_h', 'max_h', 'priority',
              'aspect', 'chars', 'required', 'rel', 'text']
OUT_COLS = ['id', 'kind', 'col', 'row', 'cols', 'rows',
            'x', 'y', 'w', 'h',          # px, origen arriba-izquierda
            'tx', 'ty', 'sx', 'sy',      # centro/escala en px, origen abajo-izquierda (TD)
            'text']


class EditorialSolverExt:

    def __init__(self, ownerComp):
        self.ownerComp = ownerComp
        # Migrate older components to a single custom parameter page.
        if hasattr(ownerComp.par, 'Blockcount'):
            solver_page = next((p for p in ownerComp.customPages
                                if p.name == 'Solver'), None)
            if solver_page is not None:
                ownerComp.par.Blockcount.page = solver_page
                for page in list(ownerComp.customPages):
                    if page.name == 'Pieza' and not page.pars:
                        page.destroy()
        self._results = queue.Queue()
        self._busy = False
        self._pending = False      # se pidió otro solve mientras uno corría
        self._t0 = 0.0

    # ------------------------------------------------------------------ API

    def Solve(self):
        """Lanza un solve en segundo plano con los parámetros actuales."""
        if self._busy:
            self._pending = True
            return
        try:
            solver = self._solverModule()
            blocks = self._readBlocks(solver)
            page = self._readPage(solver)
            page.validate()
        except Exception as e:
            self._setStatus('ERROR: ' + str(e))
            debug(e)
            return

        p = self.ownerComp.par
        args = (solver, blocks, page, int(p.Seed.eval()), float(p.Timelimit.eval()),
                int(p.Workers.eval()))
        self._busy = True
        self._t0 = time.perf_counter()
        self._setStatus('solving…')
        threading.Thread(target=self._worker, args=args, daemon=True).start()

    def Resizeblocks(self):
        """Resize input rows; keep removed rows in storage for later reuse."""
        comp = self.ownerComp
        count = max(1, int(comp.par.Blockcount.eval()))
        table = comp.op('blocks_in')
        cached = comp.fetch('block_rows_cache', {})
        current = [[cell.val for cell in table.row(r)] for r in range(1, table.numRows)]
        for i, row in enumerate(current):
            cached[i] = row
        header = [cell.val for cell in table.row(0)]
        rows = [header]
        for i in range(count):
            if i in cached:
                rows.append(cached[i])
            else:
                values = dict(id='bloque_' + str(i + 1), kind='image',
                              min_w=1, max_w=0, min_h=1, max_h=0,
                              priority=1, aspect='', chars=0, required=1,
                              rel='', text='')
                rows.append([values.get(key, '') for key in header])
        comp.store('block_rows_cache', cached)
        table.text = '\n'.join('\t'.join(map(str, row)) for row in rows)
        self.Solve()

    def Poll(self):
        """Llamar cada frame (frame_exec). Vuelca resultados listos a layout_out."""
        try:
            res = self._results.get_nowait()
        except queue.Empty:
            return
        self._busy = False
        self._write(res)
        if self._pending:
            self._pending = False
            self.Solve()

    # ------------------------------------------------------------ internos

    def _worker(self, solver, blocks, page, seed, time_limit, workers):
        try:
            res = solver.solve(blocks, page, seed=seed, time_limit=time_limit, workers=workers)
        except Exception as e:
            res = {'status': 'ERROR: ' + str(e), 'objective': None, 'blocks': []}
        res['page_h'] = page.height
        self._results.put(res)

    def _solverModule(self):
        lib = self.ownerComp.par.Libpath.eval()
        # append (no insert): los paquetes de TD (numpy) deben tener prioridad.
        if lib and lib not in sys.path:
            sys.path.append(lib)
        return self.ownerComp.op('editorial_solver').module

    def _readPage(self, solver):
        p = self.ownerComp.par
        return solver.Page(cols=int(p.Cols), rows=int(p.Rows),
                           width=float(p.Pagew), height=float(p.Pageh),
                           margin=float(p.Margin), gutter=float(p.Gutter),
                           row_gutter=float(p.Rowpadding),
                           chars_per_module=int(p.Charspermodule))

    def _readBlocks(self, solver):
        t = self.ownerComp.op('blocks_in')
        header = [c.val for c in t.row(0)]
        blocks = []
        for r in range(1, t.numRows):
            row = {h: t[r, h].val.strip() for h in header}
            if not row.get('id'):
                continue

            def num(k, d=0, f=int):
                v = row.get(k, '')
                return f(v) if v not in ('', None) else d

            blocks.append(solver.Block(
                id=row['id'],
                kind=row.get('kind') or 'text',
                min_w=num('min_w', 1), max_w=num('max_w', 0),
                min_h=num('min_h', 1), max_h=num('max_h', 0),
                priority=num('priority', 1),
                aspect=num('aspect', 0.0, float),
                chars=num('chars', 0) or len(row.get('text', '')),
                required=row.get('required', '1') not in ('0', 'false', 'False', 'no'),
                rel=row.get('rel', '').split(),
                text=row.get('text', ''),
            ))
        return blocks

    def _write(self, res):
        out = self.ownerComp.op('layout_out')
        out.clear()
        out.appendRow(OUT_COLS)
        page_h = res.get('page_h', 0)
        for b in res['blocks']:
            tx = b['x'] + b['w'] / 2
            ty = page_h - (b['y'] + b['h'] / 2)
            out.appendRow([b['id'], b['kind'], b['col'], b['row'], b['cols'], b['rows'],
                           round(b['x'], 2), round(b['y'], 2), round(b['w'], 2), round(b['h'], 2),
                           round(tx, 2), round(ty, 2), round(b['w'], 2), round(b['h'], 2),
                           b['text']])
        if res['status'] in ('OPTIMAL', 'FEASIBLE'):
            self._syncMedia(res['blocks'])
        ms = (time.perf_counter() - self._t0) * 1000
        obj = res.get('objective')
        self._setStatus('{}  {:.0f} ms  obj={}  bloques={}'.format(
            res['status'], ms, obj, len(res['blocks'])))
        preview = self.ownerComp.op('preview')
        if preview is not None:
            preview.cook(force=True)

    def _syncMedia(self, blocks):
        """Feed a native Replicator; never create content nodes in Python."""
        comp = self.ownerComp
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
        replicator.nodeX, replicator.nodeY = 0, 0
        rows = [['name', 'id', 'kind', 'x', 'y', 'w', 'h']]
        for block in blocks:
            slug = re.sub(r'[^a-zA-Z0-9_]', '_', block['id'])[:40]
            digest = hashlib.sha256(block['id'].encode('utf-8')).hexdigest()[:12]
            rows.append(['movie_' + slug + '_' + digest, block['id'], block['kind'],
                         block['x'], block['y'], block['w'], block['h']])
        # One update avoids removing/recreating nodes between clear and append.
        table.text = '\n'.join('\t'.join(map(str, row)) for row in rows)
        replicator.par.template = table.path
        mapping = comp.op('media_map')
        if mapping is None:
            mapping = comp.create(tableDAT, 'media_map')
            mapping.nodeX, mapping.nodeY = 1000, -200
        active = {row[0] for row in rows[1:]}
        map_rows = [['id', 'kind', 'movie_top', 'active', 'x', 'y', 'w', 'h']]
        for row in rows[1:]:
            map_rows.append([row[1], row[2], media.path + '/' + row[0], 1] + row[3:])
        for node in media.children:
            block_id = node.fetch('layout_block_id', None)
            if block_id is not None and node.name not in active:
                map_rows.append([block_id, '', node.path, 0, '', '', '', ''])
        mapping.text = '\n'.join('\t'.join(map(str, row)) for row in map_rows)

    def _setStatus(self, msg):
        self.ownerComp.par.Status = msg


MEDIA_CALLBACKS = """def onReplicate(comp, allOps, newOps, template, master):
    for node in allOps:
        for r in range(1, template.numRows):
            if template[r, 'name'].val == node.name:
                node.store('layout_block_id', template[r, 'id'].val)
                node.store('layout_active', True)
                node.store('layout_rect', {k: float(template[r, k].val)
                                          for k in ('x', 'y', 'w', 'h')})
                node.comment = 'Content for block: ' + template[r, 'id'].val
                break
    return

def onRemoveReplicant(comp, replicant):
    # Retain assigned files when optional blocks leave the solution.
    replicant.store('layout_active', False)
    return
"""
