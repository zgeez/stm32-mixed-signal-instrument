"""Hardware-independent package and command smoke checks."""

import subprocess
import sys

import stm32_msi


def test_package_imports():
    assert stm32_msi.__name__ == "stm32_msi"


def test_module_entry_point():
    result = subprocess.run(
        [sys.executable, "-m", "stm32_msi", "--help"], capture_output=True, text=True, check=True
    )
    assert "--port" in result.stdout
    assert result.stderr == ""
