"""
EditorialSolverExt — Extension para un Base COMP en TouchDesigner.

Lee  ./blocks_in   (Table DAT, una fila por bloque)
Escribe ./layout_out (Table DAT, rectángulos resueltos)

El solve corre en un hilo (CP-SAT libera el GIL), así TD no se congela.
El hilo NUNCA toca operadores: deja el resultado en una cola y Poll(),
llamado cada frame por ./frame_exec, lo vuelca a layout_out en el hilo principal.
"""

import hashlib
import queue
import re
import sys
import threading
import time

WEIGHT_PARS = {
    'coverage': 'Wcoverage',
    'area': 'Warea',
    'aspect': 'Waspect',
    'optional': 'Woptional',
    'column': 'Wcolumn',
}


SOLVING = 'solving…'
UNCHANGED = '  (sin cambios)'


class EditorialSolverExt:
    def __init__(self, ownerComp):
        self.ownerComp = ownerComp
        self._results = queue.Queue()
        self._busy = False
        self._pending = False  # se pidió otro solve mientras uno corría
        self._t0 = 0.0
        self._lastBlocks = None  # bloques del último resultado válido (hint)
        self._lastKey = None  # clave de entrada del último resultado válido
        # Si TD reinicializa la extensión (p. ej. al recargar este archivo) durante
        # un solve, el hilo entrega el resultado a la instancia anterior. Se relanza.
        if str(ownerComp.par.Status.eval()).startswith(SOLVING):
            run('args[0].Solve()', self, delayFrames=1)

    # ------------------------------------------------------------------ API

    def Solve(self):
        """Lanza un solve en segundo plano con los parámetros actuales."""
        if self._busy:
            self._pending = True
            return
        try:
            self._config()  # falla aquí, antes de lanzar el hilo, si falta el DAT
            solver = self._solverModule()
            blocks = self._readBlocks(solver)
            page = self._readPage(solver)
            weights = self._readWeights(solver)
            # Errores de entrada al instante, en el hilo principal.
            page.validate()
            weights.validate()
            solver.validate_blocks(blocks, page)
        except Exception as e:
            self._lastKey = None  # Status ya no describe el último resultado
            self._setStatus('ERROR: ' + str(e))
            debug(e)
            return

        p = self.ownerComp.par
        seed, limit, workers = int(p.Seed.eval()), float(p.Timelimit.eval()), int(p.Workers.eval())
        det = bool(p.Deterministic.eval()) if hasattr(p, 'Deterministic') else False
        key = repr((blocks, page, seed, limit, workers, weights, det))
        if key == self._lastKey:
            # Status ya describe ese resultado; solo se marca, sin reemplazarlo.
            status = str(p.Status.eval())
            if not status.endswith(UNCHANGED):
                self._setStatus(status + UNCHANGED)
            return
        self._busy = True
        self._t0 = time.perf_counter()
        self._setStatus(SOLVING)
        threading.Thread(
            target=self._worker,
            args=(solver, blocks, page, seed, limit, workers, weights, det, self._lastBlocks, key),
            daemon=True,
        ).start()

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
                values = dict(self._config().NEW_BLOCK_ROW, id='bloque_' + str(i + 1))
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

    def _worker(self, solver, blocks, page, seed, time_limit, workers, weights, det, hint, key):
        try:
            res = solver.solve(
                blocks,
                page,
                seed=seed,
                time_limit=time_limit,
                workers=workers,
                weights=weights,
                hint=hint,
                deterministic=det,
            )
        except Exception as e:
            res = {'status': 'ERROR: ' + str(e), 'objective': None, 'blocks': []}
        res['page_h'] = page.height
        res['key'] = key
        self._results.put(res)

    def _config(self):
        dat = self.ownerComp.op('layout_config')
        if dat is None:
            raise RuntimeError('falta el DAT layout_config; ejecuta update_workflow.py')
        return dat.module

    def _solverModule(self):
        lib = self.ownerComp.par.Libpath.eval()
        # append (no insert): los paquetes de TD (numpy) deben tener prioridad.
        if lib and lib not in sys.path:
            sys.path.append(lib)
        return self.ownerComp.op('editorial_solver').module

    def _readPage(self, solver):
        p = self.ownerComp.par
        return solver.Page(
            cols=int(p.Cols.eval()),
            rows=int(p.Rows.eval()),
            width=float(p.Pagew.eval()),
            height=float(p.Pageh.eval()),
            margin=float(p.Margin.eval()),
            gutter=float(p.Gutter.eval()),
            row_gutter=float(p.Rowpadding.eval()),
            chars_per_module=int(p.Charspermodule.eval()),
        )

    def _readWeights(self, solver):
        defaults = solver.Weights()
        p = self.ownerComp.par
        vals = {}
        for field, name in WEIGHT_PARS.items():
            par = getattr(p, name, None)
            vals[field] = int(par.eval()) if par is not None else getattr(defaults, field)
        return solver.Weights(**vals)

    def _readBlocks(self, solver):
        t = self.ownerComp.op('blocks_in')
        rows = [[cell.val for cell in t.row(r)] for r in range(t.numRows)]
        return solver.blocks_from_rows(rows[0], rows[1:]) if rows else []

    def _write(self, res):
        out = self.ownerComp.op('layout_out')
        out.clear()
        out.appendRow(list(self._config().OUTPUT_COLUMNS))
        page_h = res.get('page_h', 0)
        for b in res['blocks']:
            tx = b['x'] + b['w'] / 2
            ty = page_h - (b['y'] + b['h'] / 2)
            out.appendRow(
                [
                    b['id'],
                    b['kind'],
                    b['col'],
                    b['row'],
                    b['cols'],
                    b['rows'],
                    round(b['x'], 2),
                    round(b['y'], 2),
                    round(b['w'], 2),
                    round(b['h'], 2),
                    round(tx, 2),
                    round(ty, 2),
                    round(b['w'], 2),
                    round(b['h'], 2),
                    b['text'],
                ]
            )
        ok = res['status'] in ('OPTIMAL', 'FEASIBLE')
        self._lastKey = None
        if ok:
            self._lastBlocks = res['blocks']
            self._lastKey = res.get('key')
            if not self._syncMedia(res['blocks']):
                return
        ms = (time.perf_counter() - self._t0) * 1000
        msg = '{}  {:.0f} ms  obj={}  bloques={}'.format(
            res['status'], ms, res.get('objective'), len(res['blocks'])
        )
        if res['status'].startswith('ERROR'):
            msg = res['status']
        elif res['status'] == 'INFEASIBLE' and res.get('conflicts'):
            msg = 'INFEASIBLE  conflicto: ' + ', '.join(map(str, res['conflicts']))
        self._setStatus(msg)
        preview = self.ownerComp.op('preview')
        if preview is not None:
            preview.cook(force=True)

    def _syncMedia(self, blocks):
        """Feed the native Replicator; the infrastructure comes from setup_media()."""
        comp = self.ownerComp
        media = comp.op('media_inputs')
        table = media.op('replicate_table') if media is not None else None
        mapping = comp.op('media_map')
        if table is None or mapping is None:
            self._setStatus('ERROR: falta la infraestructura de medios; ejecuta update_workflow.py')
            return False
        rows = [['name', 'id', 'kind', 'x', 'y', 'w', 'h']]
        for block in blocks:
            slug = re.sub(r'[^a-zA-Z0-9_]', '_', block['id'])[:40]
            digest = hashlib.sha256(block['id'].encode('utf-8')).hexdigest()[:12]
            rows.append(
                [
                    'movie_' + slug + '_' + digest,
                    block['id'],
                    block['kind'],
                    block['x'],
                    block['y'],
                    block['w'],
                    block['h'],
                ]
            )
        # One update avoids removing/recreating nodes between clear and append.
        table.text = '\n'.join('\t'.join(map(str, row)) for row in rows)
        active = {row[0] for row in rows[1:]}
        map_rows = [['id', 'kind', 'movie_top', 'active', 'x', 'y', 'w', 'h']]
        for row in rows[1:]:
            map_rows.append([row[1], row[2], media.path + '/' + row[0], 1, *row[3:]])
        for node in media.children:
            block_id = node.fetch('layout_block_id', None)
            if block_id is not None and node.name not in active:
                map_rows.append([block_id, '', node.path, 0, '', '', '', ''])
        mapping.text = '\n'.join('\t'.join(map(str, row)) for row in map_rows)
        return True

    def _setStatus(self, msg):
        # Status es una sola línea: los errores de validación llegan en varias.
        self.ownerComp.par.Status = '; '.join(str(msg).splitlines())
