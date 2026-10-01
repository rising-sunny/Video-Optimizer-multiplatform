"""Shim: mantiene el CLI tras mover el modulo a pipeline/."""
from pipeline.microdoc_analytics import main

if __name__ == "__main__":
    import sys

    sys.exit(main())