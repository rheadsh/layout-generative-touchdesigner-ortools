"""
editorial_solver.py — Solver de maquetación editorial con OR-Tools CP-SAT.

Módulo puro (sin dependencias de TouchDesigner) para poder probarlo fuera de TD
y luego importarlo desde una Extension.

Modelo
------
La página es una retícula de COLS x ROWS módulos. Cada bloque (titular, imagen,
texto, pie de foto, cita…) es un rectángulo entero (x, y, w, h) en módulos.

Restricciones duras
  * Todos los bloques dentro de la retícula.
  * Ningún par de bloques se solapa (AddNoOverlap2D).
  * Rango de tamaño min/max por bloque.
  * Bloques de texto: área >= área necesaria para su número de caracteres.
  * Orden de lectura: el bloque i+1 empieza "después" que el bloque i
    (más abajo, o a la misma altura y más a la derecha).
  * Relaciones: 'below:<id>' (pie de foto pegado bajo su imagen, mismo ancho),
    'right:<id>', 'top' (anclado arriba), 'fullwidth'.
  * Bloques opcionales (required=0) pueden quedar fuera de la página.

Objetivo (maximizar)
  + cobertura de la página (módulos ocupados)
  - desviación del área "objetivo" de cada bloque (proporcional a su prioridad)
  - desviación de la proporción deseada (imágenes)
  + presencia de bloques opcionales
  - distancia a una columna preferida aleatoria (solo seed != 0) → variaciones
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ortools.sat.python import cp_model


@dataclass
class Block:
    id: str
    kind: str = "text"            # headline | image | text | caption | quote | ...
    min_w: int = 1
    max_w: int = 0                # 0 = sin límite (= cols)
    min_h: int = 1
    max_h: int = 0                # 0 = sin límite (= rows)
    priority: int = 1             # peso en el objetivo
    aspect: float = 0.0           # ancho/alto deseado en px (0 = libre)
    chars: int = 0                # caracteres de texto (solo bloques de texto)
    required: bool = True
    rel: list[str] = field(default_factory=list)   # ['below:img1', 'top', 'fullwidth']
    text: str = ""                # contenido, se pasa tal cual a la salida


@dataclass
class Page:
    cols: int = 12
    rows: int = 16
    width: float = 1080.0         # px
    height: float = 1440.0
    margin: float = 48.0
    gutter: float = 12.0
    chars_per_module: int = 60    # capacidad tipográfica de un módulo de texto

    row_gutter: float | None = None  # None conserva el medianil uniforme

    @property
    def vertical_gutter(self) -> float:
        return self.gutter if self.row_gutter is None else self.row_gutter

    def validate(self):
        if self.cols < 1 or self.rows < 1 or self.chars_per_module < 1:
            raise ValueError("Columnas, filas y capacidad deben ser mayores que cero")
        if min(self.margin, self.gutter, self.vertical_gutter) < 0:
            raise ValueError("Margen y padding no pueden ser negativos")
        if self.cell_w <= 0 or self.cell_h <= 0:
            raise ValueError("La resolución no deja espacio útil: reduce margen o padding")

    @property
    def cell_w(self) -> float:
        return (self.width - 2 * self.margin - (self.cols - 1) * self.gutter) / self.cols

    @property
    def cell_h(self) -> float:
        return (self.height - 2 * self.margin - (self.rows - 1) * self.vertical_gutter) / self.rows


def solve(blocks: list[Block], page: Page, seed: int = 0, time_limit: float = 2.0,
          workers: int = 8, reading_order: bool = True) -> dict:
    """Resuelve la maquetación. Devuelve {'status', 'objective', 'blocks': [...]}."""
    page.validate()
    C, R = page.cols, page.rows
    m = cp_model.CpModel()
    rng = random.Random(seed)
    by_id = {b.id: i for i, b in enumerate(blocks)}

    xs, ys, ws, hs, present, areas = [], [], [], [], [], []
    x_iv, y_iv = [], []

    for b in blocks:
        max_w = min(b.max_w or C, C)
        max_h = min(b.max_h or R, R)
        min_w = min(b.min_w, max_w)
        min_h = min(b.min_h, max_h)
        if "fullwidth" in b.rel:
            min_w = max_w = C

        x = m.NewIntVar(0, C - 1, f"x_{b.id}")
        y = m.NewIntVar(0, R - 1, f"y_{b.id}")
        w = m.NewIntVar(min_w, max_w, f"w_{b.id}")
        h = m.NewIntVar(min_h, max_h, f"h_{b.id}")
        p = m.NewConstant(1) if b.required else m.NewBoolVar(f"p_{b.id}")

        xe = m.NewIntVar(0, C, f"xe_{b.id}")
        ye = m.NewIntVar(0, R, f"ye_{b.id}")
        m.Add(xe == x + w)
        m.Add(ye == y + h)

        x_iv.append(m.NewOptionalIntervalVar(x, w, xe, p, f"ix_{b.id}"))
        y_iv.append(m.NewOptionalIntervalVar(y, h, ye, p, f"iy_{b.id}"))

        a = m.NewIntVar(0, C * R, f"a_{b.id}")
        m.AddMultiplicationEquality(a, [w, h])

        xs.append(x); ys.append(y); ws.append(w); hs.append(h)
        present.append(p); areas.append(a)

    # 1. Sin solapes.
    m.AddNoOverlap2D(x_iv, y_iv)

    objective = []
    total_prio = sum(max(b.priority, 1) for b in blocks)
    for i, b in enumerate(blocks):
        x, y, w, h, p, a = xs[i], ys[i], ws[i], hs[i], present[i], areas[i]

        # 2. Capacidad de texto: w*h módulos * chars_per_module >= chars.
        if b.chars > 0:
            need = -(-b.chars // page.chars_per_module)  # ceil
            m.Add(a >= need).OnlyEnforceIf(p)

        # 3. Proporción deseada (en px). Penaliza |w*cw - r*h*ch|.
        if b.aspect > 0:
            S = 100
            lhs = int(page.cell_w * S)
            rhs = int(b.aspect * page.cell_h * S)
            dev = m.NewIntVar(0, (C * lhs + R * rhs), f"dev_{b.id}")
            m.AddAbsEquality(dev, w * lhs - h * rhs)
            # Normaliza a décimas de módulo para que pese comparable al área.
            dev_mod = m.NewIntVar(0, (C + R) * 10 * max(1, rhs // max(lhs, 1) + 1), f"devm_{b.id}")
            m.AddDivisionEquality(dev_mod, dev * 10, max(lhs, 1))
            objective.append(-3 * dev_mod)

        # 4. Relaciones.
        for r in b.rel:
            if r == "top":
                m.Add(y == 0).OnlyEnforceIf(p)
            elif r.startswith("below:") and r[6:] in by_id:
                j = by_id[r[6:]]
                m.Add(y == ys[j] + hs[j]).OnlyEnforceIf([p, present[j]])
                m.Add(x == xs[j]).OnlyEnforceIf([p, present[j]])
                m.Add(w == ws[j]).OnlyEnforceIf([p, present[j]])
                m.AddImplication(p, present[j])
            elif r.startswith("right:") and r[6:] in by_id:
                j = by_id[r[6:]]
                m.Add(x == xs[j] + ws[j]).OnlyEnforceIf([p, present[j]])
                m.Add(y == ys[j]).OnlyEnforceIf([p, present[j]])
                m.AddImplication(p, present[j])

        # 5. Objetivo.
        # 5a. Cobertura: cada módulo ocupado suma (llena la página).
        objective.append(2 * a)
        # 5b. Jerarquía: área objetivo proporcional a la prioridad (+ jitter por seed).
        share = b.priority * rng.uniform(0.8, 1.25) / total_prio
        target = max(1, int(C * R * share))
        miss = m.NewIntVar(0, C * R, f"miss_{b.id}")
        m.AddAbsEquality(miss, a - target)
        objective.append(-4 * miss)
        # 5c. Bloques opcionales: premio por aparecer.
        if not b.required:
            objective.append(6 * target * p)
        # 5d. Variación: columna preferida aleatoria según seed.
        if seed:
            pref = rng.randint(0, C - 1)
            off = m.NewIntVar(0, C, f"off_{b.id}")
            m.AddAbsEquality(off, x - pref)
            objective.append(-2 * off)

    # 6. Orden de lectura en raster (fila mayor primero) entre bloques presentes.
    #    Todos los pares: si un opcional desaparece, la cadena no se rompe.
    if reading_order:
        for i in range(len(blocks)):
            for k in range(i + 1, len(blocks)):
                m.Add(ys[i] * C + xs[i] <= ys[k] * C + xs[k]).OnlyEnforceIf(
                    [present[i], present[k]])

    m.Maximize(sum(objective))

    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_limit
    s.parameters.num_search_workers = workers
    s.parameters.random_seed = seed
    status = s.Solve(m)

    out = {"status": s.StatusName(status), "objective": None, "blocks": []}
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return out
    out["objective"] = s.ObjectiveValue()

    cw, ch, g, mg = page.cell_w, page.cell_h, page.gutter, page.margin
    gy_padding = page.vertical_gutter
    for i, b in enumerate(blocks):
        if not s.Value(present[i]):
            continue
        gx, gy, gw, gh = (s.Value(v) for v in (xs[i], ys[i], ws[i], hs[i]))
        out["blocks"].append({
            "id": b.id, "kind": b.kind, "text": b.text,
            "col": gx, "row": gy, "cols": gw, "rows": gh,
            # px, origen arriba-izquierda
            "x": mg + gx * (cw + g),
            "y": mg + gy * (ch + gy_padding),
            "w": gw * cw + (gw - 1) * g,
            "h": gh * ch + (gh - 1) * gy_padding,
        })
    return out
