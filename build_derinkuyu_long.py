"""Shim: mantiene el CLI tras mover el modulo a pipeline/."""
from pipeline.build_derinkuyu_long import main

if __name__ == "__main__":
    import sys

    sys.exit(main())