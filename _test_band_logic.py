"""Verify band logic: under min triggers expansion, over max triggers compression."""

# Replicate the local _band_distance helper
def band_distance(words, min_w, max_w):
    if words < min_w:
        return min_w - words
    if words > max_w:
        return words - max_w
    return 0

# Replicate the per-iteration decision
def needs_action(words, min_w, max_w):
    below = words < min_w
    above = words > max_w
    if below:
        return "expansion"
    if above:
        return "compression"
    return None

# 60s short: min=80%×target, max=110%×target
DURATION = 60
TARGET = int(DURATION * 2.5)        # 150
MIN = int(DURATION * 0.80 * 2.5)    # 120
MAX = int(TARGET * 1.10)            # 165

cases = [
    ("Caso real fallido (gpt-oss-120b)", 57),
    ("Caso real fallido v2 (llama 70b)", 70),
    ("Caso real OVERshoot (llama 70b retry)", 378),
    ("Caso ideal", 138),
    ("Caso justo en min", 120),
    ("Caso justo en max", 132),
    ("Bajo el min", 100),
    ("Sobre el max", 200),
]

print(f"Banda objetivo para Short 60s: {MIN}–{MAX} palabras")
print()
print(f"{'Caso':<40} {'Palabras':>10} {'Distancia':>10} {'Acción':>15}")
print("-" * 80)
for name, words in cases:
    action = needs_action(words, MIN, MAX) or "ninguna"
    dist = band_distance(words, MIN, MAX)
    print(f"{name:<40} {words:>10} {dist:>10} {action:>15}")

# Simulate the ping-pong scenario: 70 → 378 → ?
print()
print("=" * 80)
print("Simulación del caso real:")
print("=" * 80)
current = 70
print(f"  Inicial: {current} palabras → distancia {band_distance(current, MIN, MAX)} ({needs_action(current, MIN, MAX)})")

current = 378  # after expansion retry
print(f"  Tras expansión: {current} palabras → distancia {band_distance(current, MIN, MAX)} ({needs_action(current, MIN, MAX)})")
# Should detect it's now over max → trigger compression on next iteration

# After compression, hopefully something like 145
current_after_compression = 145
print(f"  Tras compresión: {current_after_compression} palabras → distancia {band_distance(current_after_compression, MIN, MAX)} ({needs_action(current_after_compression, MIN, MAX) or 'dentro de banda'})")
