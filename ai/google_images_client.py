"""
Compatibilidad legacy para codigo que aun importa GoogleImagesClient.

Google Images fue retirado. Este modulo reutiliza el cliente actual de
Openverse (gratis, sin API key) manteniendo nombres antiguos.
"""

from media.bing_images_client import BingImagesClient


class GoogleImagesClient(BingImagesClient):
    """Alias retrocompatible que usa Openverse por defecto."""

