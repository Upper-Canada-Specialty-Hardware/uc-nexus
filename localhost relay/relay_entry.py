"""PyInstaller entry script.

The bundled exe runs this as __main__ with no package context, so it uses an ABSOLUTE import (a relative
`from .cli` would fail here). `python -m ucnexus_relay` uses src/ucnexus_relay/__main__.py instead, where
relative imports work. Both just call the same CLI dispatcher.
"""

import sys

from ucnexus_relay.cli import main

if __name__ == "__main__":
    sys.exit(main())
