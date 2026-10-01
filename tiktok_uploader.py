"""Shim: mantiene el CLI tras mover el modulo a publish/."""
from publish.tiktok_uploader import main

if __name__ == "__main__":
    import sys

    sys.exit(main())