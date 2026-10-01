"""Shim: mantiene el CLI tras mover el modulo a channel/."""
from channel.trend_report import main

if __name__ == "__main__":
    import sys

    sys.exit(main())