"""Shim: mantiene el CLI tras mover el modulo a pipeline/."""
from pipeline.daily_short_pipeline import main

if __name__ == "__main__":
    import sys

    sys.exit(main())