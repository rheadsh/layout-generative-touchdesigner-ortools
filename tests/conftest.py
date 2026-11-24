import pytest

import layout_config
from editorial_solver import Page, blocks_from_rows


@pytest.fixture
def sample_blocks():
    return blocks_from_rows(layout_config.BLOCK_COLUMNS, layout_config.SAMPLE_ROWS)


@pytest.fixture
def page():
    return Page()
