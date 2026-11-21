"""Step 0 smoke test: the package and all Phase 1 libraries can be imported."""

import importlib

import pytest

import insightflow

PHASE1_LIBRARIES = ["pandas", "numpy", "openpyxl", "yaml", "pydantic", "pandera"]
STAGES = ["ingestion", "profiling", "normalization", "cleaning", "validation", "audit", "pipeline"]


def test_package_has_version():
    assert insightflow.__version__ == "0.1.0"


@pytest.mark.parametrize("name", PHASE1_LIBRARIES)
def test_phase1_library_installed(name):
    importlib.import_module(name)


@pytest.mark.parametrize("stage", STAGES)
def test_stage_module_exists(stage):
    importlib.import_module(f"insightflow.{stage}")
