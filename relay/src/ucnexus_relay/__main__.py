"""`python -m ucnexus_relay` and the PyInstaller analysis entry point both run the CLI dispatcher."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
