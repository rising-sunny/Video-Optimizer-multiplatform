"""Shim: mantiene el CLI tras mover el modulo a channel/."""
from channel.performance_feedback import main

if __name__ == "__main__":
    import sys

    sys.exit(main())