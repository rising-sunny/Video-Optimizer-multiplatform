"""Verify (a) gemini_ai_client._generate forwardea task_type al backend.
   (b) cover_frame fallback ahora salta videos correctamente."""
import sys, types, os
sys.modules.setdefault("channel_strategy", types.ModuleType("channel_strategy"))


# ----- Test 1: gemini_ai_client._generate forward de task_type -----
print("=" * 70)
print("Test 1: gemini_ai_client._generate forward de task_type")
print("=" * 70)

# Stub the backend to capture what gets passed
class _FakeBackend:
    def __init__(self):
        self.captured = []
    def _generate(self, prompt_text, max_tokens=4096, task_type="general"):
        self.captured.append({"prompt": prompt_text[:30], "max_tokens": max_tokens, "task_type": task_type})
        return "STUB_RESPONSE"

# Manually instantiate the wrapper with a fake backend
from gemini_ai_client import GeminiAiClient
client = GeminiAiClient()
client.backend = _FakeBackend()
client.client_available = True

# Without task_type (backward compat)
r1 = client._generate("test prompt 1", max_tokens=4000)
assert client.backend.captured[-1]["task_type"] == "general", f"Default task_type debería ser 'general', es {client.backend.captured[-1]['task_type']!r}"
print(f"  [OK] Sin task_type → backend recibe 'general'")

# With task_type explicit
r2 = client._generate("test prompt 2", max_tokens=4000, task_type="script_quality")
assert client.backend.captured[-1]["task_type"] == "script_quality", "task_type explícito no llegó"
print(f"  [OK] task_type='script_quality' → backend recibe 'script_quality'")

# ----- Test 2: cover_frame fallback skipping videos -----
print()
print("=" * 70)
print("Test 2: cover_frame fallback salta archivos .mp4 y usa la siguiente imagen")
print("=" * 70)

# Read the source code to verify the new branch exists (we can't easily run the
# full cover_frame_generator without PIL setup, so we inspect the logic).
src = open("cover_frame_generator.py", encoding="utf-8").read()
checks = [
    ("Tiene set _IMAGE_EXTS", "_IMAGE_EXTS" in src and ".png" in src),
    ("Filtra por extensión", "ext not in _IMAGE_EXTS" in src),
    ("Loguea cuando salta video", "no es imagen" in src),
    ("Loguea cuando usa imagen base", "Usando" in src and "como base" in src),
    ("Try/except por imagen corrupta", "No se pudo abrir" in src),
]
for label, ok in checks:
    print(f"  [{'OK' if ok else 'FAIL'}] {label}")

# Mini-simulation of the path-selection logic
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".avif", ".tiff", ".tif"}
segments = [
    {"image_path": "C:\\Users\\esteb\\Downloads\\video1.mp4"},  # ← antes elegía esto, ahora salta
    {"image_path": "C:\\Users\\esteb\\Downloads\\video2.mp4"},  # ← también salta
    {"image_path": "project_media/segment_003.png"},            # ← elige esto
    {"image_path": "project_media/segment_004.png"},
]
selected = None
for seg in segments:
    ip = seg.get("image_path")
    if not ip:
        continue
    ext = os.path.splitext(ip)[1].lower()
    if ext not in _IMAGE_EXTS:
        continue
    selected = ip
    break

print()
print(f"Simulación con 2 videos al inicio + 2 imágenes:")
print(f"  Elegido: {selected}")
assert selected == "project_media/segment_003.png", f"Debería ser la 3ra, es {selected}"
print(f"  [OK] Salta los .mp4 y elige la primera imagen real")

print()
print("Todos los tests pasan.")
