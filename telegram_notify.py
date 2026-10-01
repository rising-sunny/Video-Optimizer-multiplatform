"""Shim: mantiene el CLI tras mover el modulo a publish/."""
from publish.telegram_notify import main

if __name__ == "__main__":
    import sys

    sys.exit(main())