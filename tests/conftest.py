import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import data_generator as gen  # noqa: E402
from app.services.common import make_cfg  # noqa: E402
from run_workflow import run_pipeline  # noqa: E402


def starter_args(seed=20261022):
    return SimpleNamespace(seed=seed, merchants=40, orders=1000, attempts=1100, batches=20, bank_lines=100)


def build(path, seed=20261022):
    gen.generate_to(str(path), make_cfg(starter_args(seed)))
    return run_pipeline(str(path), formats=("csv", "json", "sql"))


@pytest.fixture(scope="session")
def starter(tmp_path_factory):
    path = tmp_path_factory.mktemp("starter")
    return path, build(path)
