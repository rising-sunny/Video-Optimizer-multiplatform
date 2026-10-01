"""Shim: mantiene el CLI `python catharsis_editor.py` tras mover el modulo a catharsis/."""
from catharsis.catharsis_editor import main

if __name__ == "__main__":
    import sys

    sys.exit(main())