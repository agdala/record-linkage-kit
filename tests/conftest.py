from pathlib import Path

import pandas as pd
import pytest

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample"


@pytest.fixture(scope="session")
def sample_dir() -> Path:
    return SAMPLE


@pytest.fixture(scope="session")
def sample_bases() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    read = lambda name: pd.read_csv(SAMPLE / name, dtype=str, keep_default_na=False)  # noqa: E731
    return read("base_a.csv"), read("base_b.csv"), read("gabarito.csv")
