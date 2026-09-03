import tempfile
from pathlib import Path
import pytest

from src.provisioning.db import init_db, get_connection


@pytest.fixture()
def tmp_db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return db_path
