"""Entry point: ``python -m mxstudio.kit …`` (see :mod:`mxstudio.kit.cli`)."""
import sys

from .cli import main

sys.exit(main())
