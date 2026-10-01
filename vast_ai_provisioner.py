"""Shim: mantiene el CLI `python vast_ai_provisioner.py` tras mover el módulo a infra/."""
from infra.vast_ai_provisioner import _main

if __name__ == "__main__":
    import sys

    sys.exit(_main())