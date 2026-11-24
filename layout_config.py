"""
layout_config.py — Datos compartidos entre el solver, las pruebas y TouchDesigner.

Módulo sin dependencias (ni OR-Tools ni TouchDesigner) para que el constructor
de la red pueda cargarlo desde el Textport sin preparar ``sys.path``.
"""

# Columnas de ``blocks_in``; coinciden con los campos de ``editorial_solver.Block``.
BLOCK_COLUMNS = (
    'id',
    'kind',
    'min_w',
    'max_w',
    'min_h',
    'max_h',
    'priority',
    'aspect',
    'chars',
    'required',
    'rel',
    'text',
)

# Valores de una fila nueva de ``blocks_in`` al aumentar ``Blockcount``.
NEW_BLOCK_ROW = {
    'kind': 'image',
    'min_w': 1,
    'max_w': 0,
    'min_h': 1,
    'max_h': 0,
    'priority': 1,
    'aspect': '',
    'chars': 0,
    'required': 1,
    'rel': '',
    'text': '',
}

# Columnas de ``layout_out``.
OUTPUT_COLUMNS = (
    'id',
    'kind',
    'col',
    'row',
    'cols',
    'rows',
    'x',
    'y',
    'w',
    'h',  # px, origen arriba-izquierda
    'tx',
    'ty',
    'sx',
    'sy',  # centro/tamaño en px, origen abajo-izquierda (TD)
    'text',
)

# Bloques de ejemplo: encabezado + filas, en el mismo orden que BLOCK_COLUMNS.
SAMPLE_ROWS = (
    ('titular', 'headline', 6, 0, 2, 3, 5, '', '', 1, 'top', 'La ciudad que se reinventa'),
    ('foto1', 'image', 4, 0, 4, 0, 4, 1.5, '', 1, '', ''),
    ('pie1', 'caption', 1, 0, 1, 1, 1, '', '', 1, 'below:foto1', 'Vista aérea del centro'),
    ('cuerpo1', 'text', 3, 6, 1, 0, 2, '', 1800, 1, '', ''),
    ('cita', 'quote', 3, 6, 2, 3, 3, '', '', 0, '', '«Diseñar es decidir»'),
    ('foto2', 'image', 3, 0, 3, 0, 3, 0.8, '', 0, '', ''),
    ('cuerpo2', 'text', 3, 6, 1, 0, 2, '', 1500, 1, '', ''),
)

# Paleta de la previsualización (hex) por tipo de bloque.
KIND_COLORS = {
    'headline': '#111111',
    'image': '#c9c3b8',
    'text': '#e8e4dc',
    'caption': '#f4d35e',
    'quote': '#ee6c4d',
}
DEFAULT_COLOR = '#999999'


def hex_to_rgb(color):
    """'#rrggbb' -> (r, g, b) en 0..1."""
    color = color.lstrip('#')
    return tuple(int(color[i : i + 2], 16) / 255 for i in (0, 2, 4))


def sample_table():
    """Encabezado + filas de ejemplo, listo para una Table DAT."""
    return [list(BLOCK_COLUMNS)] + [list(row) for row in SAMPLE_ROWS]
