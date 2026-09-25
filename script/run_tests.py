"""One-click test runner: pytest + coverage report for src/ (fails under 80%)."""
from __future__ import annotations

import sys

import pytest

if __name__ == "__main__":
    sys.exit(pytest.main(["--cov=src", "--cov-report=term-missing", "--cov-fail-under=80", *sys.argv[1:]]))
