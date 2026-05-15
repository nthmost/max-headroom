"""
Top-level pytest config. Adds the intake/ dir to sys.path so tests can
`import db`, `import downloader`, etc. without the package needing a real
install. Mirrors how the running service actually imports them.
"""

import os
import sys

# tests/ -> intake/
INTAKE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if INTAKE_DIR not in sys.path:
    sys.path.insert(0, INTAKE_DIR)
