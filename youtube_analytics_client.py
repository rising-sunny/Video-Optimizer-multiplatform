"""Shim: mantiene el CLI tras mover el modulo a channel/."""
from channel.youtube_analytics_client import main

if __name__ == "__main__":
    import sys

    sys.exit(main())