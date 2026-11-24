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

Objetivo (maximizar, ponderado por ``Weights``)
  + cobertura de la página (módulos ocupados)
  - desviación del área "objetivo" de cada bloque (proporcional a su prioridad)
  - desviación de la proporción deseada (imágenes)
  + presencia de bloques opcionales
  - distancia a una columna preferida aleatoria (solo seed != 0) → variaciones

Si el modelo no tiene solución, ``solve`` devuelve en ``conflicts`` un conjunto
de bloques requeridos que no caben juntos.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TypedDict

from ortools.sat.python import cp_model

# Relaciones admitidas en Block.rel.
FLAG_RELATIONS = ('top', 'fullwidth')
TARGET_RELATIONS = ('below', 'right')

# Todos los términos del objetivo se multiplican por _OBJ_SCALE para expresar la
# desviación de proporción en centésimas de módulo sin divisiones en el modelo.
_OBJ_SCALE = 10
_ASPECT_PRECISION = 100  # debe ser _OBJ_SCALE * 10 (ver término de proporción)


@dataclass
class Block:
    id: str
    kind: str = "text"  # headline | image | text | caption | quote | ...
    min_w: int = 1
    max_w: int = 0  # 0 = sin límite (= cols)
    min_h: int = 1
    max_h: int = 0  # 0 = sin límite (= rows)
    priority: int = 1  # peso en el objetivo
    aspect: float = 0.0  # ancho/alto deseado en px (0 = libre)
    chars: int = 0  # caracteres de texto (solo bloques de texto)
    required: bool = True
    rel: list[str] = field(default_factory=list)  # ['below:img1', 'top', 'fullwidth']
    text: str = ""  # contenido, se pasa tal cual a la salida


@dataclass
class Page:
    cols: int = 12
    rows: int = 16
    width: float = 1080.0  # px
    height: float = 1440.0
    margin: float = 48.0
    gutter: float = 12.0
    chars_per_module: int = 60  # capacidad tipográfica de un módulo de texto
    row_gutter: float | None = None  # None conserva el medianil uniforme

    @property
    def vertical_gutter(self) -> float:
        return self.gutter if self.row_gutter is None else self.row_gutter

    @property
    def cell_w(self) -> float:
        return (self.width - 2 * self.margin - (self.cols - 1) * self.gutter) / self.cols

    @property
    def cell_h(self) -> float:
        return (self.height - 2 * self.margin - (self.rows - 1) * self.vertical_gutter) / self.rows

    def validate(self) -> None:
        if self.cols < 1 or self.rows < 1 or self.chars_per_module < 1:
            raise ValueError("Columnas, filas y capacidad deben ser mayores que cero")
        if min(self.margin, self.gutter, self.vertical_gutter) < 0:
            raise ValueError("Margen y padding no pueden ser negativos")
        if self.cell_w <= 0 or self.cell_h <= 0:
            raise ValueError("La resolución no deja espacio útil: reduce margen o padding")


@dataclass
class Weights:
    """Pesos del objetivo. Valores enteros >= 0."""

    coverage: int = 2  # por módulo ocupado
    area: int = 4  # por módulo de diferencia con el área objetivo
    aspect: int = 3  # por décima de módulo de desviación de proporción
    optional: int = 6  # por módulo del área objetivo de un opcional presente
    column: int = 2  # por columna de distancia a la columna preferida (seed != 0)

    def validate(self) -> None:
        for name, value in vars(self).items():
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"Peso '{name}' debe ser un entero >= 0")


class PlacedBlock(TypedDict):
    id: str
    kind: str
    text: str
    col: int
    row: int
    cols: int
    rows: int
    x: float  # px, origen arriba-izquierda
    y: float
    w: float
    h: float


class LayoutResult(TypedDict):
    status: str
    objective: float | None
    blocks: list[PlacedBlock]
    conflicts: list[str]  # ids de bloques requeridos incompatibles (solo INFEASIBLE)


def parse_relation(rel: str) -> tuple[str, str | None]:
    """'below:foto1' -> ('below', 'foto1'); 'top' -> ('top', None)."""
    kind, sep, target = rel.partition(':')
    return (kind, target) if sep else (rel, None)


_FALSE_VALUES = ('0', 'false', 'no')


def _parse_number(value, kind: type, default, where: str):
    text = str(value).strip()
    if text == '':
        return default
    try:
        return kind(text)
    except ValueError:
        label = 'un entero' if kind is int else 'un número'
        raise ValueError(f"{where}: '{text}' no es {label}") from None


def blocks_from_rows(header: Sequence[str], rows: Sequence[Sequence]) -> list[Block]:
    """Convierte filas de tabla (texto o números) en bloques.

    Las celdas vacías toman el valor por defecto de ``Block``; las filas sin id se
    omiten; ``chars`` vacío o 0 usa la longitud de ``text``. Los errores indican la
    fila (1 = primera fila de datos) y la columna.
    """
    defaults = Block(id='')
    blocks = []
    for n, values in enumerate(rows, start=1):
        row = {k: str(v).strip() for k, v in zip(header, values, strict=False)}
        if not row.get('id'):
            continue

        def num(key, kind=int, row=row, n=n):
            return _parse_number(row.get(key, ''), kind, getattr(defaults, key), f"fila {n}, {key}")

        text = row.get('text', '')
        blocks.append(
            Block(
                id=row['id'],
                kind=row.get('kind') or defaults.kind,
                min_w=num('min_w'),
                max_w=num('max_w'),
                min_h=num('min_h'),
                max_h=num('max_h'),
                priority=num('priority'),
                aspect=num('aspect', float),
                chars=num('chars') or len(text),
                required=row.get('required', '1').lower() not in _FALSE_VALUES,
                rel=row.get('rel', '').split(),
                text=text,
            )
        )
    return blocks


def _size_bounds(b: Block, page: Page) -> tuple[int, int, int, int]:
    """(min_w, max_w, min_h, max_h) efectivos en módulos."""
    max_w = b.max_w or page.cols
    max_h = b.max_h or page.rows
    min_w = b.min_w
    if "fullwidth" in b.rel:
        min_w = max_w = page.cols
    return min_w, max_w, b.min_h, max_h


def validate_blocks(blocks: Sequence[Block], page: Page) -> None:
    """Lanza ValueError con todos los problemas de entrada encontrados."""
    errors: list[str] = []
    ids = [b.id for b in blocks]
    seen: set[str] = set()
    for n, b in enumerate(blocks, start=1):
        name = f"'{b.id}'" if b.id else f"#{n}"
        if not b.id:
            errors.append(f"Bloque #{n}: falta id")
        elif b.id in seen:
            errors.append(f"Bloque {name}: id duplicado")
        seen.add(b.id)

        if b.min_w < 1 or b.min_h < 1:
            errors.append(f"Bloque {name}: min_w y min_h deben ser >= 1")
        if b.max_w < 0 or b.max_h < 0:
            errors.append(f"Bloque {name}: max_w y max_h deben ser >= 0")
        if b.max_w and b.min_w > b.max_w:
            errors.append(f"Bloque {name}: min_w ({b.min_w}) > max_w ({b.max_w})")
        if b.max_h and b.min_h > b.max_h:
            errors.append(f"Bloque {name}: min_h ({b.min_h}) > max_h ({b.max_h})")
        if "fullwidth" in b.rel:
            if b.max_w and b.max_w < page.cols:
                errors.append(f"Bloque {name}: fullwidth exige max_w 0 o >= {page.cols}")
        elif b.min_w > page.cols:
            errors.append(f"Bloque {name}: min_w ({b.min_w}) supera las {page.cols} columnas")
        if b.min_h > page.rows:
            errors.append(f"Bloque {name}: min_h ({b.min_h}) supera las {page.rows} filas")
        if b.priority < 0 or b.aspect < 0 or b.chars < 0:
            errors.append(f"Bloque {name}: priority, aspect y chars no pueden ser negativos")

        if b.chars > 0:
            _, max_w, _, max_h = _size_bounds(b, page)
            need = -(-b.chars // page.chars_per_module)
            capacity = min(max_w, page.cols) * min(max_h, page.rows)
            if need > capacity:
                errors.append(
                    f"Bloque {name}: {b.chars} caracteres necesitan {need} módulos; "
                    f"caben {capacity}"
                )

        for rel in b.rel:
            kind, target = parse_relation(rel)
            if target is None and kind in FLAG_RELATIONS:
                continue
            if kind not in TARGET_RELATIONS or not target:
                errors.append(f"Bloque {name}: relación desconocida '{rel}'")
            elif target == b.id:
                errors.append(f"Bloque {name}: '{rel}' apunta a sí mismo")
            elif target not in ids:
                errors.append(f"Bloque {name}: '{rel}' apunta a un id inexistente")
    if errors:
        raise ValueError("\n".join(errors))


@dataclass
class _Vars:
    x: list = field(default_factory=list)
    y: list = field(default_factory=list)
    w: list = field(default_factory=list)
    h: list = field(default_factory=list)
    area: list = field(default_factory=list)
    present: list = field(default_factory=list)


def _build_model(
    blocks: Sequence[Block],
    page: Page,
    seed: int,
    weights: Weights,
    reading_order: bool,
    diagnose: bool,
) -> tuple[cp_model.CpModel, _Vars]:
    """Construye el modelo. Con ``diagnose`` todos los bloques son opcionales y
    no hay objetivo: la presencia de los requeridos se impone con supuestos."""
    C, R = page.cols, page.rows
    m = cp_model.CpModel()
    v = _Vars()
    by_id = {b.id: i for i, b in enumerate(blocks)}
    x_iv, y_iv = [], []

    for b in blocks:
        min_w, max_w, min_h, max_h = _size_bounds(b, page)
        x = m.NewIntVar(0, C - 1, f"x_{b.id}")
        y = m.NewIntVar(0, R - 1, f"y_{b.id}")
        w = m.NewIntVar(min_w, max_w, f"w_{b.id}")
        h = m.NewIntVar(min_h, max_h, f"h_{b.id}")
        p = m.NewConstant(1) if b.required and not diagnose else m.NewBoolVar(f"p_{b.id}")

        xe = m.NewIntVar(0, C, f"xe_{b.id}")
        ye = m.NewIntVar(0, R, f"ye_{b.id}")
        x_iv.append(m.NewOptionalIntervalVar(x, w, xe, p, f"ix_{b.id}"))
        y_iv.append(m.NewOptionalIntervalVar(y, h, ye, p, f"iy_{b.id}"))

        a = m.NewIntVar(0, C * R, f"a_{b.id}")
        m.AddMultiplicationEquality(a, [w, h])

        for values, var in ((v.x, x), (v.y, y), (v.w, w), (v.h, h), (v.area, a), (v.present, p)):
            values.append(var)

    # 1. Sin solapes.
    m.AddNoOverlap2D(x_iv, y_iv)

    objective = []
    rng = random.Random(seed)
    total_prio = sum(max(b.priority, 1) for b in blocks)
    ratio_unit = page.cell_h / page.cell_w
    for i, b in enumerate(blocks):
        x, y, w, h, p, a = v.x[i], v.y[i], v.w[i], v.h[i], v.present[i], v.area[i]

        # 2. Capacidad de texto: w*h módulos * chars_per_module >= chars.
        if b.chars > 0:
            need = -(-b.chars // page.chars_per_module)  # ceil
            m.Add(a >= need).OnlyEnforceIf(p)

        # 3. Relaciones.
        for rel in b.rel:
            kind, target = parse_relation(rel)
            if kind == "top":
                m.Add(y == 0).OnlyEnforceIf(p)
            elif kind in TARGET_RELATIONS:
                j = by_id[target]
                both = [p, v.present[j]]
                if kind == "below":
                    m.Add(y == v.y[j] + v.h[j]).OnlyEnforceIf(both)
                    m.Add(x == v.x[j]).OnlyEnforceIf(both)
                    m.Add(w == v.w[j]).OnlyEnforceIf(both)
                else:
                    m.Add(x == v.x[j] + v.w[j]).OnlyEnforceIf(both)
                    m.Add(y == v.y[j]).OnlyEnforceIf(both)
                m.AddImplication(p, v.present[j])

        if diagnose:
            continue

        # 4. Proporción deseada en centésimas de módulo: |P*w - round(P*r)*h|,
        #    con r = aspect * cell_h / cell_w (ancho en módulos por módulo de alto).
        if b.aspect > 0:
            P = _ASPECT_PRECISION
            k = round(P * b.aspect * ratio_unit)
            dev = m.NewIntVar(0, P * C + k * R, f"dev_{b.id}")
            m.AddAbsEquality(dev, P * w - k * h)
            # P/10 centésimas = una décima de módulo; _OBJ_SCALE * 10 == P, así que
            # el coeficiente por centésima es exactamente weights.aspect.
            objective.append(-weights.aspect * dev)

        # 5. Objetivo.
        # 5a. Cobertura: cada módulo ocupado suma (llena la página).
        objective.append(_OBJ_SCALE * weights.coverage * a)
        # 5b. Jerarquía: área objetivo proporcional a la prioridad (+ jitter por seed).
        share = b.priority * rng.uniform(0.8, 1.25) / total_prio
        target_area = max(1, int(C * R * share))
        miss = m.NewIntVar(0, C * R, f"miss_{b.id}")
        m.AddAbsEquality(miss, a - target_area)
        objective.append(-_OBJ_SCALE * weights.area * miss)
        # 5c. Bloques opcionales: premio por aparecer.
        if not b.required:
            objective.append(_OBJ_SCALE * weights.optional * target_area * p)
        # 5d. Variación: columna preferida aleatoria según seed.
        if seed:
            pref = rng.randint(0, C - 1)
            off = m.NewIntVar(0, C, f"off_{b.id}")
            m.AddAbsEquality(off, x - pref)
            objective.append(-_OBJ_SCALE * weights.column * off)

    # 6. Orden de lectura en raster (fila mayor primero) entre bloques presentes.
    #    El orden es transitivo: basta con comparar cada bloque con los siguientes
    #    hasta el primer requerido (incluido), que siempre está presente.
    if reading_order:
        for i in range(len(blocks)):
            for k in range(i + 1, len(blocks)):
                m.Add(v.y[i] * C + v.x[i] <= v.y[k] * C + v.x[k]).OnlyEnforceIf(
                    [v.present[i], v.present[k]]
                )
                if blocks[k].required and not diagnose:
                    break

    if objective:
        m.Maximize(sum(objective))
    return m, v


def _add_hints(
    m: cp_model.CpModel, blocks: Sequence[Block], v: _Vars, hint: Sequence[Mapping]
) -> None:
    """Parte de una solución previa (mismo formato que LayoutResult['blocks'])."""
    previous = {h["id"]: h for h in hint}
    for i, b in enumerate(blocks):
        h = previous.get(b.id)
        if not b.required:
            m.AddHint(v.present[i], h is not None)
        if h is None:
            continue
        for var, key in ((v.x[i], "col"), (v.y[i], "row"), (v.w[i], "cols"), (v.h[i], "rows")):
            m.AddHint(var, int(h[key]))


def _find_conflicts(
    blocks: Sequence[Block], page: Page, reading_order: bool, time_limit: float
) -> list[str]:
    """Bloques requeridos que, juntos, hacen el modelo infactible."""
    m, v = _build_model(blocks, page, 0, Weights(), reading_order, diagnose=True)
    required = [i for i, b in enumerate(blocks) if b.required]
    m.AddAssumptions([v.present[i] for i in required])
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_limit
    s.parameters.num_workers = 1  # los supuestos de infactibilidad requieren un hilo
    if s.Solve(m) != cp_model.INFEASIBLE:
        return []
    core = set(s.SufficientAssumptionsForInfeasibility())
    ids = {blocks[i].id for i in required if v.present[i].Index() in core}
    # Un bloque con below:/right: obliga a su destino a estar presente: se incluye
    # el destino para que el conflicto nombre también, p. ej., la foto de un pie.
    by_id = {b.id: b for b in blocks}
    stack = list(ids)
    while stack:
        for rel in by_id[stack.pop()].rel:
            kind, target = parse_relation(rel)
            if kind in TARGET_RELATIONS and target not in ids:
                ids.add(target)
                stack.append(target)
    return [b.id for b in blocks if b.id in ids]


def solve(
    blocks: Sequence[Block],
    page: Page,
    seed: int = 0,
    time_limit: float = 2.0,
    workers: int = 8,
    reading_order: bool = True,
    weights: Weights | None = None,
    hint: Sequence[Mapping] | None = None,
    deterministic: bool = False,
) -> LayoutResult:
    """Resuelve la maquetación.

    ``hint``: bloques de una solución anterior para acelerar re-solves pequeños.
    ``deterministic``: misma semilla → mismo resultado aunque no se demuestre el
    óptimo (usa tiempo determinista en lugar de tiempo de reloj).
    Lanza ValueError si la página, los bloques o los pesos no son válidos.
    """
    weights = weights or Weights()
    page.validate()
    weights.validate()
    validate_blocks(blocks, page)

    m, v = _build_model(blocks, page, seed, weights, reading_order, diagnose=False)
    if hint:
        _add_hints(m, blocks, v, hint)

    s = cp_model.CpSolver()
    if deterministic:
        s.parameters.max_deterministic_time = time_limit
        s.parameters.interleave_search = True
        s.parameters.max_time_in_seconds = time_limit * 10  # red de seguridad
    else:
        s.parameters.max_time_in_seconds = time_limit
    s.parameters.num_workers = workers
    s.parameters.random_seed = seed
    status = s.Solve(m)

    out: LayoutResult = {
        "status": s.StatusName(status),
        "objective": None,
        "blocks": [],
        "conflicts": [],
    }
    if status == cp_model.INFEASIBLE:
        out["conflicts"] = _find_conflicts(blocks, page, reading_order, time_limit)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return out
    out["objective"] = s.ObjectiveValue() / _OBJ_SCALE

    cw, ch, g, mg = page.cell_w, page.cell_h, page.gutter, page.margin
    gv = page.vertical_gutter
    for i, b in enumerate(blocks):
        if not s.Value(v.present[i]):
            continue
        gx, gy, gw, gh = (s.Value(var) for var in (v.x[i], v.y[i], v.w[i], v.h[i]))
        out["blocks"].append(
            {
                "id": b.id,
                "kind": b.kind,
                "text": b.text,
                "col": gx,
                "row": gy,
                "cols": gw,
                "rows": gh,
                "x": mg + gx * (cw + g),
                "y": mg + gy * (ch + gv),
                "w": gw * cw + (gw - 1) * g,
                "h": gh * ch + (gh - 1) * gv,
            }
        )
    return out
