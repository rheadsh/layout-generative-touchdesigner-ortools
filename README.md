# Layout generativo para TouchDesigner

Workflow de layout automático con Python y OR-Tools CP-SAT. Distribuye bloques
sobre una retícula sin solapes y genera entradas Movie File In TOP mediante un
Replicator COMP para asignar imágenes o videos.

## Requisitos e instalación

- TouchDesigner con Python 3.11 (el workflow se creó en 2025.33230).
- uv para preparar las dependencias declaradas en `pyproject.toml`.

Desde la raíz del proyecto:

```bash
uv sync --locked
```

Se utiliza Python 3.11 y `numpy==2.1.2`. TouchDesigner no ejecuta el intérprete de
`.venv`: la extensión agrega su directorio `site-packages` al final de `sys.path`,
para dar prioridad a las librerías incluidas en TouchDesigner.

`uv.lock` y `.python-version` deben permanecer en el repositorio. `.venv` y las
cachés locales se excluyen con `.gitignore`.

## Abrir o construir el workflow

Abre `TouchDesigner/layout_workflow.toe` o arrastra `TouchDesigner/editorial_solver.tox` a tu red.
El componente del proyecto está en `/project1/editorial_solver`.

Para construirlo desde los scripts, ejecuta en el Textport de TouchDesigner:

```python
exec(open('/ruta/layout-generative/TouchDesigner/build_network.py', encoding='utf-8-sig').read())
```

Los scripts localizan la raíz del proyecto con la variable de entorno
`LAYOUT_GENERATIVE_DIR`; si no existe, la buscan en la carpeta del `.toe` o en su
carpeta padre (por ejemplo, `TouchDesigner/layout_workflow.toe`).

**El constructor reemplaza el componente `editorial_solver` existente.** Guarda
antes los cambios que quieras conservar. Para actualizar el componente existente
sin reconstruirlo (agrega parámetros nuevos, `layout_config` y la infraestructura
de medios que falte), ejecuta:

```python
exec(open('/ruta/layout-generative/TouchDesigner/update_workflow.py', encoding='utf-8-sig').read())
```

Los DATs de Python están vinculados a archivos en disco. Al mover el proyecto,
actualiza sus rutas y `Libpath`, que en macOS apunta a
`.venv/lib/python3.11/site-packages`. Mantén el timeline reproduciéndose para que
`frame_exec` recoja los resultados del solver.

## Parámetros

Los controles están en una sola página, **Solver**:

| Parámetro | Uso |
|---|---|
| `Pagew`, `Pageh` | Resolución de la pieza: ancho y alto en píxeles. |
| `Blockcount` | Número de bloques de entrada; ajusta las filas de `blocks_in`. |
| `Gutter` | Padding entre columnas en píxeles. |
| `Rowpadding` | Padding entre filas en píxeles. |
| `Margin` | Margen exterior en píxeles. |
| `Cols`, `Rows` | Número de columnas y filas de la retícula. |
| `Solve`, `Autosolve` | Resolver manualmente o al cambiar parámetros y bloques. |
| `Seed` | Variación de la distribución. |
| `Charspermodule` | Capacidad tipográfica estimada por módulo. |
| `Timelimit`, `Workers` | Tiempo máximo y número de hilos del solver. |
| `Wcoverage`, `Warea`, `Waspect`, `Woptional`, `Wcolumn` | Pesos del objetivo (0–20): cobertura de la página, área según prioridad, proporción de imágenes, presencia de opcionales y variación por columna. |
| `Deterministic` | La misma `Seed` produce siempre el mismo layout, aunque no se demuestre el óptimo. |
| `Libpath`, `Status` | Ruta de dependencias y estado del cálculo. |

La resolución también acepta expresiones como `op('/project1/mi_top').width` y
`op('/project1/mi_top').height`. Las filas retiradas al reducir `Blockcount` se
conservan en el almacenamiento del componente para recuperarlas después. Los
bloques adicionales son imágenes requeridas sin proporción fija. Los bloques
opcionales pueden quedar fuera de una solución, por lo que el número de bloques
visibles puede ser menor al número de entrada.

## Entrada: `blocks_in`

Una fila por bloque; su orden define el orden de lectura.

| Columna | Significado |
|---|---|
| `id` | Identificador único y estable del bloque. |
| `kind` | Tipo: `headline`, `image`, `text`, `caption`, `quote` u otro. |
| `min_w`, `max_w`, `min_h`, `max_h` | Tamaño en módulos; máximo 0 significa sin límite adicional. |
| `priority` | Peso relativo del área deseada. |
| `aspect` | Proporción ancho/alto deseada; vacío significa libre. |
| `chars` | Cantidad de caracteres; si está vacío se usa la longitud de `text`. |
| `required` | 1: requerido; 0: puede omitirse. |
| `rel` | Relaciones separadas por espacios: `top`, `fullwidth`, `below:<id>`, `right:<id>`. |
| `text` | Contenido que se conserva en la salida. |

## Salida y contenido

`layout_out` contiene las posiciones resueltas:

- `x`, `y`, `w`, `h`: rectángulo en píxeles, con origen arriba a la izquierda.
- `tx`, `ty`, `sx`, `sy`: centro y tamaño en píxeles, con origen abajo a la izquierda.
- `col`, `row`, `cols`, `rows`: posición y tamaño en módulos.

Dentro de `media_inputs`, `replicate_table` alimenta un **Replicator COMP** que
replica `movie_master`, un Movie File In TOP. Asigna el contenido en el parámetro
**File** de cada réplica. `media_map` relaciona los ids con los TOPs y sus rectángulos.
Los nombres estables permiten conservar los archivos asignados al volver a resolver;
las réplicas ausentes se conservan y se marcan con `active=0` en `media_map`.

`preview` muestra los rectángulos de color. El constructor conecta esa vista a
`OUT_layout`; en el proyecto guardado la salida puede llamarse `out1`.
La previsualización todavía no compone las imágenes o videos: conecta las entradas
al render final utilizando los rectángulos de `layout_out` o `media_map`.

## Validación y diagnóstico

Antes de resolver se valida la entrada: ids vacíos o duplicados, `min_*` mayor que
`max_*` o que la retícula, valores negativos, texto que no cabe y relaciones
desconocidas o hacia ids inexistentes. Los errores aparecen en `Status` con la fila
y la columna. Si no hay solución (`INFEASIBLE`), `Status` indica qué bloques
requeridos no caben juntos.

Con Autosolve, cada cálculo parte de la solución anterior y se omite si la entrada
no cambió.

## Archivos

| Archivo | Función |
|---|---|
| `editorial_solver.py` | Modelo CP-SAT independiente de TouchDesigner, validación y lectura de filas. |
| `layout_config.py` | Columnas, bloques de ejemplo y colores compartidos (sin dependencias). |
| `TouchDesigner/EditorialSolverExt.py` | Lectura de parámetros, cálculo en segundo plano y actualización de resultados. |
| `TouchDesigner/build_network.py` | Constructor de la red e infraestructura de medios. |
| `TouchDesigner/update_workflow.py` | Actualizador del componente existente. |
| `TouchDesigner/preview_top.py` | Callbacks de la previsualización Script TOP. |
| `TouchDesigner/editorial_solver.tox` | Componente reutilizable. |
| `TouchDesigner/layout_workflow.toe` | Proyecto de TouchDesigner. |
| `tests/` | Pruebas con pytest del solver y comprobaciones estáticas de los scripts de TD. |
| `scripts/render_previews.py` | Genera los SVG de `previews/`. |
| `previews/` | Ejemplos de layouts en SVG. |

## Desarrollo

`uv sync` instala también las herramientas de desarrollo (pytest y ruff). Desde la
raíz del proyecto:

```bash
uv run pytest
```

```bash
uv run ruff check .
```

```bash
uv run ruff format .
```

```bash
uv run python scripts/render_previews.py previews
```

Las pruebas cubren el solver (geometría, relaciones, validación, diagnóstico,
determinismo) y comprueban que los scripts de TouchDesigner compilan y que sus
pesos coinciden con los del solver. La integración de operadores se verifica dentro
de TouchDesigner. La configuración de ruff está en `pyproject.toml`; declara como
globales los nombres que TouchDesigner inyecta (`op`, `parent`, `baseCOMP`…).
