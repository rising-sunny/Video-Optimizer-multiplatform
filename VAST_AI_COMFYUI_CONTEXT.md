# Vast.ai + ComfyUI — Contexto operativo

## ✅ Estado 2026-06-05

- **Instancia activa y lista (detenida):** `39656888` · **RTX A4000 16GB** ·
  compute_cap **860** (Ampere, compatible con FLUX) · ssh7.vast.ai:16888 · $0.0815/hr.
- FLUX Schnell + Dev descargados y ComfyUI verificado por HTTP. `.env` ya apunta a ella.
- Detenida; la app la auto-enciende al generar y la apaga al terminar.
- Pre-provisionada con `vast_ai_provisioner.py` (filtro compute_cap>=750 corrigió el
  problema de la Titan Xp Pascal del 2026-06-04).

### Bug encontrado y corregido hoy: GPU incompatible (Pascal)
El auto-failover eligio una **Titan Xp** (Pascal, compute_cap 610). Paso los filtros
(CPU AVX2 ✓, 12GB ✓) pero su GPU es demasiado vieja para el PyTorch cu128 de la imagen
ComfyUI → `CUDA error: no kernel image is available for execution on the device` en el
KSampler. El modelo cargaba pero el sampler reventaba; luego venian ConnectionReset.

**Fix aplicado en `vast_ai_provisioner.py`:**
- Nuevo filtro `compute_cap >= 750` (Turing+). Excluye Pascal (Titan Xp=610, Tesla
  P100=600, GTX 10xx) y anteriores. Constante `DEFAULT_MIN_COMPUTE_CAP=750`.
- Vast expone la compute capability como el entero `compute_cap` (750=sm_75, 860=sm_86).
- Reintentos con backoff en las llamadas de API (`_http`) para sobrevivir cortes
  transitorios `RemoteDisconnected` de Vast.ai.
- La RTX 3060 compatible mas barata queda ~$0.062-0.082/hr.

### Tabla rapida de compatibilidad GPU
| compute_cap | Arq | Ejemplos | ¿Sirve? |
|---|---|---|---|
| 600, 610 | Pascal | Tesla P100, Titan Xp, GTX 10xx | ❌ NO |
| 700 | Volta | V100, Titan V, GV100 | ⚠️ excluido por el filtro (sin probar) |
| 750 | Turing | RTX 20xx, T4, Titan RTX, Q RTX | ✅ |
| 860 | Ampere | RTX 30xx, A4000/A5000 | ✅ (recomendado, barato) |
| 890 | Ada | RTX 40xx | ✅ |
| 1200 | Blackwell | RTX 50xx | ✅ |

---

## 🤖 Auto-failover automatizado (2026-06-03)

Toda la secuencia manual de "Setup de instancia nueva" de más abajo ahora está
**automatizada** en código:

- **`vast_ai_provisioner.py` (NUEVO):** busca oferta verificada con AVX2, crea la
  instancia, la arranca, adjunta la SSH key, configura `/etc/portal.yaml`, descarga
  los 2 checkpoints FLUX y verifica ComfyUI por HTTP. Lógica pura (filtro AVX2,
  ranking de ofertas, reescritura de `.env`) testeada offline.
- **`vast_ai_instance_manager.py`:** cuando `start_instance()` recibe un error fatal
  donde rentar otra máquina ayudaría (`resources_unavailable`, `no_such_instance`),
  y `VAST_AUTO_FAILOVER=1`, llama al provisioner, actualiza el `.env`, destruye la
  instancia muerta y reintenta — todo en una sola pasada. Se intenta **una sola vez**
  por sesión (sin runaway de instancias pagadas).
- **NO** se dispara con `insufficient_credit` (rentar otra fallaría igual).
- Activar con `VAST_AUTO_FAILOVER=1` en `.env`. Default OFF porque rentar cuesta dinero
  y el aprovisionamiento tarda ~10-20 min (descarga ~34GB).

Funciones reutilizables: `cpu_supports_avx2(cpu_name)`, `rank_offers(offers)`,
`update_env_file(path, updates)`, `read_ssh_pubkey()`, `VastProvisioner(api_key).provision()`.

---

## Estado actualizado (2026-06-03 ~21:13 America/Santiago)

**Instancia ACTIVA y configurada (detenida, lista para auto-encenderse).**

- **ID:** 39379708 · RTX 3060 12GB · Xeon E5-1660 v3 (AVX2 OK) · $0.083/hr
- **SSH:** ssh4.vast.ai:19708
- **Modelos FLUX:** Schnell + Dev descargados y verificados (ComfyUI responde por HTTP).
- **Estado:** detenida tras provisionar; la app la enciende al generar y la apaga al terminar.
- **Provisionada automaticamente** con `python vast_ai_provisioner.py` (driver one-shot),
  pipeline completo en ~7 min. Crédito de Vast.ai ya recargado (el bloqueo de
  `insufficient_credit` quedó resuelto).

Si esta instancia muere (`resources_unavailable`), con `VAST_AUTO_FAILOVER=1` la app
renta una nueva sola; o se reprovisiona a mano con `python vast_ai_provisioner.py`.

## ⚠️ PROBLEMA PENDIENTE (2026-05-22 ~16:30)

**Instancia 37289130 (RTX 3060) NO arranca:**
```
PUT /instances/37289130/ {"state":"running"}
→ {"success": false, "error": "resources_unavailable",
   "msg": "Required resources are currently unavailable, state change queued."}
```

El host físico que tenía la RTX 3060 ya no está disponible. Vast.ai aceptó "queue"
la petición pero no la honra. La app reintenta `ensure_ready()` por cada segmento
y cada falla cuesta ~10 min de polling vacío.

### Acción pendiente (al retomar la sesión)

1. **Cancelar generación activa en la app** si sigue corriendo
2. **Destruir instancia 37289130** (sigue cobrando ~$0.013/hr de storage):
   ```python
   DELETE /api/v0/instances/37289130/
   ```
3. **Buscar nueva oferta verificada con AVX2** (ver sección "Setup de instancia nueva")
4. **Provisionamiento completo:** crear → start → SSH key → portal.yaml → descargar FLUX
5. **Actualizar `.env`** con nuevo ID/SSH host/port
6. **Reiniciar app**, regenerar Mount Pelée

Tiempo estimado: 15-25 min (incluye Docker pull de ~5-15 min en host fresco).

---

## Estado de la sesión 2026-05-22

### Instancia activa (rota)
- **ID:** 37289130
- **GPU:** NVIDIA GeForce RTX 3060 12GB VRAM (host físico no disponible)
- **CPU:** AMD Ryzen 5 5600X 6-Core (AVX2 ✅)
- **SSH:** ssh2.vast.ai:19130 (no responde por host caído)
- **Docker image:** `vastai/comfy:v0.20.1-cuda-12.9-py312`
- **Status real:** `intended_status=stopped, cur_state=stopped, actual_status=exited`
- **Status_msg:** "success, running vastai/comfy_v0.20.1-cuda-12.9-py312/ssh" (stale)
- **Modelos FLUX descargados (antes del fallo):** Schnell + Dev (Comfy-Org, ~34 GB)
- **SSH key adjuntada:** ed25519 (windsurf) — id 860635

### .env actual (apunta a la instancia rota)
```
VAST_INSTANCE_ID=37289130
VAST_SSH_HOST=ssh2.vast.ai
VAST_SSH_PORT=19130
VAST_AUTO_MANAGE=1
VAST_AUTO_STOP_ON_EXIT=1
VIDEO_OPTIMIZER_SUBS_USE_WHISPER=1   # Whisper aislado en subprocess
```

---

## Cambios de código aplicados en la sesión 2026-05-22

### A. Generación de guion / storyboard (resuelve problemas de calidad)

| Archivo | Cambio | Razón |
|---|---|---|
| `tone_profile.py` (NUEVO) | Mapping centralizado categoría GUI → perfil de tono (`documentary` / `dramatic_factual` / `mystery`) | DRY entre storyboard_generator.py y claude_client.py |
| `storyboard_generator.py` | `generate_manual_prompt_text` usa perfil de tono (header, sección, channel bible, guía visual) | El system prompt era hardcoded "canal de misterios" → guion conspiranoico aunque se eligiera "Historia antigua" |
| `storyboard_generator.py` | Reglas anti-invención reformuladas: "PRIMERO profundiza con material documentado, SOLO después acorta" | Antes decía "acorta el guion" → LLM se quedaba 5x corto |
| `storyboard_generator.py` | **Contrato de longitud al TOPE del prompt** con caja Unicode y palabra "BLOQUEANTE" | Las instrucciones de duración estaban enterradas |
| `storyboard_generator.py` | **Validación post-LLM + retry bidireccional** (expansión si < min, compresión si > max). Max 2 retries | El LLM ignora el contrato y devuelve 35-72 palabras cuando el mínimo es 120 |
| `storyboard_generator.py` | Llamadas LLM usan `task_type='script_quality'` → prefiere gpt-oss-120b sobre llama-3.3-70b | gpt-oss-120b respeta mejor restricciones de longitud |
| `storyboard_generator.py` `generate_scenes_json_batched` | `MAX_TOKENS_PER_BATCH` 6000→12000 + parser tolerante (raw_decode, strip trailing commas, salvage de JSON truncado) | LLM emite visual_prompts ricos → output truncado → JSON inválido |
| `storyboard_generator.py` `combine_prompts` (en prompt_processor.py) | Devuelve solo el visual_prompt del 1er segmento del grupo (sin merge de 5 palabras random) | Inyectaba tokens basura tipo `"incorporating elements: roger, signs, faces, natural"` → FLUX dibujaba solo manos |
| `prompt_processor.py` `apply_style_to_prompt` | Ignora "No style" / vacío / estilos desconocidos (no los inyecta como literal) | Pegaba `", No style"` al final del prompt → confundía a FLUX |
| `claude_client.py` | 3 helpers por perfil (`_build_script_role_for_profile`, `_build_narrative_approach_for_profile`, `_build_script_quality_block_for_profile`) | Hardcoded "Role: Expert Scriptwriter for mysteries channel" — afectaba videos largos |
| `claude_client.py` | `generate_video_script` + `generate_video_script_with_research` + 2 refine prompts usan perfil | Mismo origen del problema en videos largos |
| `groq_client.py` | System prompt neutro para `script_quality` (antes decía "mysteries/conspiracies channel") | Sesgo a nivel system |

### B. Generación de imágenes (resuelve calidad y workflow)

| Archivo | Cambio | Razón |
|---|---|---|
| `storyboard_generator.py` | Nueva sección "REGLA VISUAL — CALIDAD CINEMATOGRAFICA" obliga 7 elementos por prompt (sujeto+acción, época, encuadre, iluminación específica, paleta+mood, calidad fotográfica, anti-artefacto) | Prompts eran formulaicos, sin dirección de cámara/iluminación |
| `storyboard_generator.py` `_build_visual_guide_for_profile` | Guía visual diferente por perfil (documentary prohíbe brillos mágicos, dramatic_factual permite catástrofes, mystery permite ambigüedad) | |
| `image_generation_manager.py` `_build_negative_prompt` | Buckets priorizados: text/UI → contextual topic-specific → AI-artifacts universales → era → quality. Antes el AI-artifact bucket llenaba el budget y el contextual nunca entraba | Faltaban anti-supernatural para histórico documental |
| `image_generation_manager.py` `build_recraft_prompt_plan` | Acepta `provider_key` (default 'recraft' para compat). Incluye cover_frames usando su visual_prompt + aspect guidance | Cover_frame se excluía → botón "Copiar Prompts" daba error "Sin prompts Recraft" |
| `image_generation_manager.py` | Auto-stop instancia Vast al terminar generación masiva (bypassa aboutToQuit que es poco fiable) | Política "just-in-time": enciende al inicio, apaga al final |
| `cover_frame_generator.py` | Fallback skipea videos (.mp4/.webm/etc) al buscar imagen base, con try/except por imagen corrupta | Si segmento 1 tiene video, PIL fallaba y caía a gradiente oscuro |
| `studio_image_handlers.py` | Nuevo helper `resolve_image_provider_key(label_or_combo)` con mapping centralizado label combo → key | DRY para que copy prompts respete el provider real |

### C. Subtítulos / Whisper

| Archivo | Cambio | Razón |
|---|---|---|
| `_whisper_subprocess_worker.py` (NUEVO) | Worker aislado que corre Whisper en su propio proceso, output JSON | torch 2.4.1+CPU crashea en c10.dll (`0xC0000005`) cuando se invoca desde Qt worker con RAM bajo (laptop tiene 5.8 GB) |
| `dynamic_subtitles_generator.py` | `generate_from_audio_and_segments` invoca subprocess en lugar de torch in-process. Timeout 1800s (override con `VIDEO_OPTIMIZER_WHISPER_TIMEOUT_S`) | Si el subprocess crashea, solo muere el subprocess. App principal sigue viva, cae al fallback de timings de segmentos |
| `burn_subs_from_project.py` (NUEVO) | Script standalone para quemar subs al MP4 existente. `--no-whisper` para deshabilitar. Detecta MP4 más reciente sin `_with_subs` en el nombre | Permite salvar un MP4 ya ensamblado sin re-correr todo |
| `.env` | `VIDEO_OPTIMIZER_SUBS_USE_WHISPER=1` (reactivado tras la isolación) | Mantener la opción de Whisper word-by-word |

### D. Persistencia y UI

| Archivo | Cambio | Razón |
|---|---|---|
| `studio_project_manager.py` `_restore_media_paths` | Removido dedup que borraba `image_path` cuando 2 segmentos compartían imagen | Rompía la agrupación "Imagen compartida · 2 segmentos" |
| `timeline_editor_widget.py` `copy_recraft_prompts_for_segment` | Newlines reales (`\n`) en lugar de literales (`\\n`) en el texto copiado | Pegaba `Prompt:\nXXX` literal al clipboard |
| `timeline_editor_widget.py` `_resolve_recraft_prompt_for_segment` | Detecta provider del combo de la GUI y lo pasa al builder | Antes hardcoded 'recraft' → copiaba prompts con boosters de Recraft aunque generaras con FLUX |
| `vast_ai_instance_manager.py` | `attach_to_qt_app(app)` conecta `aboutToQuit` además de `atexit`. Stop con timeout 10s | atexit no dispara con apps PyQt cerradas irregularmente |
| `vast_ai_instance_manager.py` | Log persistente a `~/.cache/video-optimizer/vast.log` con timestamps | Diagnóstico cuando shutdown falla |
| `video_optimizer_pyqt6.py` | Llama `attach_to_qt_app(app)` tras crear QApplication | Activa el hook |

### E. Patch one-shot aplicado

- **Proyecto Las_Guerras_Pùnicas_20260521_205412** (15-min video, primer caso): script `_patch_project_shared_images.py` propagó `image_path` del líder a follower en cada par compartido. 97/194 → 194/194 segmentos con image_path. Backup en `project.json.backup_20260522_083351.json`.

---

## Setup de una instancia nueva (paso a paso)

### 1. Buscar oferta verificada con AVX2

```python
import requests, json
api_key = "dd5d4f714595a94dc716fe9b662635978aa997f289683807afb5c09c983a0af3"
headers = {"Authorization": f"Bearer {api_key}"}

q = json.dumps({
    "gpu_ram": {"gte": 12000},
    "disk_space": {"gte": 60},
    "rentable": {"eq": True},
    "verified": {"eq": True},
    "type": "on-demand",
    "order": [["dph_total", "asc"]],
    "limit": 30
})
r = requests.get("https://console.vast.ai/api/v0/bundles/", headers=headers, params={"q": q})
offers = r.json().get("offers", [])

# Filtrar por CPU AVX2-compatible
GOOD_CPU_PATTERN = r"i7-(4|5|6|7|8|9|10|11|12|13|14)|i9-|Xeon (Gold|Silver|W|Platinum)|EPYC|Ryzen [579]|Threadripper"
import re
good_offers = [o for o in offers if re.search(GOOD_CPU_PATTERN, o.get("cpu_name", ""))]
```

### 2. CPUs que funcionan (AVX2)
- Intel 4th gen+ (Haswell): i5-4xxx, i7-4xxx, i7-10xxx, i7-12xxx, Xeon Gold/Silver/W
- AMD Zen+: EPYC 7xxx, Ryzen 5 2xxx+, Threadripper

### 3. CPUs que NO funcionan (solo AVX, sin AVX2)
- Intel i5-3570K (Ivy Bridge) → SIGILL crash al cargar la imagen Docker
- Intel Xeon E5-26xx v2 o anterior
- Cualquier CPU pre-2013

### 4. Crear la instancia
```python
offer_id = "XXXXX"
r = requests.put(
    f"https://console.vast.ai/api/v0/asks/{offer_id}/",
    headers=headers,
    json={
        "client_id": "me",
        "image": "vastai/comfy:v0.20.1-cuda-12.9-py312",
        "disk": 60,
        "onstart": "entrypoint.sh"
    }
)
instance_id = r.json()["new_contract"]
```

**NO usar `template_hash_id`** — no es necesario y puede causar problemas.

### 5. Iniciar la instancia
```python
requests.put(f"https://console.vast.ai/api/v0/instances/{instance_id}/",
             headers=headers, json={"state": "running"})
```

### 6. Esperar que arranque
- Consultar `GET /api/v0/instances/` (endpoint de lista, NO el individual)
- Estados: `None` → `loading` (Docker pull, 2-15 min) → `running`
- Si queda en `created` con `intended=stopped` → no arrancó, reintentar start o destruir

### 7. Adjuntar SSH key a la instancia (CRÍTICO)
Las keys account-level NO propagan a instancias ya corriendo:
```python
pub = "ssh-ed25519 AAAA... comment"
requests.post(f"https://console.vast.ai/api/v0/instances/{instance_id}/ssh/",
              headers=headers, json={"ssh_key": pub})
```

Public key actual del laptop: `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIL7XJOfl8QU2y74C8S8gyzA51aDW04dML6+Wrvb7aOXY windsurf`

### 8. Configurar portal.yaml
```bash
ssh -p PORT root@HOST "echo '- ComfyUI' > /etc/portal.yaml && supervisorctl restart comfyui"
```

**Formato correcto:** `- ComfyUI` (con guion-espacio al inicio).
**Formato INCORRECTO:** `ComfyUI: true` → falla el regex `^[^#].*ComfyUI`.

### 9. Descargar modelos FLUX (Comfy-Org, NO Kijai)
```bash
ssh -p PORT root@HOST "cd /workspace/ComfyUI/models/checkpoints && \
  curl -L -o flux1-schnell-fp8.safetensors 'https://huggingface.co/Comfy-Org/flux1-schnell/resolve/main/flux1-schnell-fp8.safetensors' && \
  curl -L -o flux1-dev-fp8.safetensors 'https://huggingface.co/Comfy-Org/flux1-dev/resolve/main/flux1-dev-fp8.safetensors'"
```
- Cada modelo: ~17GB, ~2.5 min a 109 MB/s
- Usar repos **Comfy-Org** (checkpoints completos con CLIP+T5+VAE)
- NO usar Kijai/flux-fp8 (solo UNet, causa `'NoneType' object has no attribute 'tokenize'`)

### 10. Verificar ComfyUI
```bash
ssh -p PORT root@HOST "curl -s http://127.0.0.1:18188/system_stats | python3 -c 'import sys,json; d=json.load(sys.stdin); g=d[\"devices\"][0]; print(f\"OK: {g[\"name\"]}  VRAM: {g[\"vram_free\"]//1024//1024}MB free\")'"
```
ComfyUI tarda 30-90s en arrancar después de que el supervisor lo inicia.

### 11. Actualizar .env local
```
VAST_INSTANCE_ID=<nuevo_id>
VAST_SSH_HOST=<ssh_host>
VAST_SSH_PORT=<ssh_port>
```

---

## Errores conocidos y soluciones

### `resources_unavailable` al hacer start (problema actual)
La máquina física ya no está disponible. Destruir instancia y crear otra.
```python
requests.delete(f"https://console.vast.ai/api/v0/instances/{id}/", headers=headers)
```
**Síntoma:** PUT con `{"state":"running"}` devuelve `{"success": false, "error": "resources_unavailable"}`. La instancia queda con `intended_status=stopped` indefinidamente.

**FIX aplicado (2026-06-03) en `vast_ai_instance_manager.py`:**
- `start_instance()` ahora inspecciona la respuesta del PUT. Si `success:false` con
  un error fatal (`resources_unavailable`, `insufficient_credit`, `no_such_instance`),
  lanza `VastStartError` en ~1ms en vez de pollear 600s (10 min).
- Circuit breaker: una vez que `ensure_ready()` recibe un error fatal, las siguientes
  llamadas cortan al instante sin volver a llamar la API. Un lote de N imágenes aborta
  en segundos, no en N×10min.
- Para reintentar tras corregir la causa (recargar saldo, nuevo `VAST_INSTANCE_ID`):
  `manager.reset_fatal_error()` o reiniciar la app.
- El mensaje de error incluye una pista accionable (crear otra oferta / recargar crédito).

### `'NoneType' object has no attribute 'tokenize'` en CLIPTextEncodeFlux
El checkpoint es UNet-only (Kijai). Necesita checkpoint completo de Comfy-Org.

### `Fatal Python error: Illegal instruction` (SIGILL)
CPU sin AVX2. Destruir instancia, buscar máquina con CPU moderno.
- Verificar: `ssh ... "grep avx2 /proc/cpuinfo | head -1"`

### `Skipping comfyui startup (not in /etc/portal.yaml)`
portal.yaml vacío o mal formateado. Escribir `- ComfyUI` (con guion-espacio al inicio).

### Instancia queda en `created` indefinidamente
Start no fue exitoso o imagen Docker incompatible. Destruir y recrear.

### `Permission denied (publickey)` al hacer SSH a instancia nueva
Las llaves SSH a nivel de cuenta (`POST /ssh/`) NO se propagan a instancias ya corriendo. Hay que adjuntarlas explícitamente:
```python
requests.post(f"https://console.vast.ai/api/v0/instances/{id}/ssh/",
              headers=headers, json={"ssh_key": "ssh-ed25519 AAAA... comment"})
```

### Docker image tarda >15 min en `loading`
Normal para primera vez en una máquina (~15GB imagen). Esperar hasta 20 min.
Si pasa de 20 min, destruir y probar otra máquina.

### Whisper crashea con `c10.dll` access violation `0xC0000005`
Bug conocido de torch 2.4.1+CPU al transcribir desde Qt worker tras FFmpeg.
**Fix aplicado en esta sesión:** Whisper aislado en subprocess (`_whisper_subprocess_worker.py`).
Si el subprocess crashea, solo muere él. La app sigue viva y cae al fallback de timings de segmentos.
**Causa principal:** RAM limitada (5.8 GB en laptop). Whisper "small" pico ~2 GB de RAM.
**Mitigación futura:** migrar a `faster-whisper` (CTranslate2, sin torch, ~75 MB en RAM con INT8).

### Cover_frame falla con "cannot identify image file" cuando segmento 1 tiene video
Fix aplicado: cover_frame_generator filtra por extensiones de imagen real (.png/.jpg/etc), salta videos.

### Guion sale demasiado corto (35-72 palabras para target 60s)
**Síntomas:** Video resulta de 14-22s en lugar de 50-60s.
**Fix aplicado:** Validación post-LLM + retry bidireccional. Si está bajo el mínimo (80% del target), pide expansión específica.
**Si el LLM sigue terco:** El prompt de expansión ahora exige "DOBLAR o TRIPLICAR" con ejemplo concreto, advierte que la respuesta SERÁ MEDIDA.

---

## Arquitectura del sistema de generación de imágenes

### Flujo: App → ComfyUI → Vast.ai
```
Usuario selecciona "ComfyUI - FLUX Dev (alta calidad)" en GUI
  → image_generation_manager.py detecta provider="comfy_dev"
  → _resolve_comfy_preset() → selecciona "historical_vertical_dev"
  → comfyui_image_client.py carga workflow JSON
  → vast_ai_instance_manager.py:
      1. ensure_ready() → start_instance() si está parada
      2. open_ssh_tunnel() → localhost:8188 ↔ remoto:18188
      3. wait_for_comfyui() → poll /system_stats
  → comfyui_image_client.py envía workflow a /prompt API
  → espera imagen vía websocket
  → descarga imagen, guarda localmente
  → image_generation_manager.py auto-stop al terminar TODA la generación
```

### Archivos clave
| Archivo | Función |
|---------|---------|
| `comfyui_image_client.py` | Cliente HTTP para ComfyUI API |
| `vast_ai_instance_manager.py` | Gestión de instancia Vast.ai (start/stop/tunnel) |
| `image_generation_manager.py` | Orquestador de providers + auto-stop tras generar |
| `comfyui_workflows/presets.json` | Mapeo de presets a workflows JSON |
| `comfyui_workflows/historical_vertical_dev.json` | Workflow FLUX Dev (25 steps) |
| `comfyui_workflows/historical_vertical_schnell.json` | Workflow FLUX Schnell (4 steps) |
| `_whisper_subprocess_worker.py` | Whisper aislado en subprocess |
| `tone_profile.py` | Mapping centralizado categoría → perfil |
| `.env` | Config de instancia (ID, SSH, timeouts, Whisper) |

### Presets disponibles
| Alias GUI | Provider key | Preset | Modelo | Steps |
|-----------|-------------|--------|--------|-------|
| ComfyUI - FLUX Schnell | comfy_schnell | historical_vertical_schnell | flux1-schnell-fp8 | 4 |
| ComfyUI - FLUX Dev (alta calidad) | comfy_dev | historical_vertical_dev | flux1-dev-fp8 | 25 |

### Parámetros de generación FLUX
- CFG: 1.0 (en KSampler), guidance: 3.5 (en CLIPTextEncodeFlux)
- Sampler: euler, Scheduler: normal
- Tamaño vertical (shorts): 768×1344
- Tamaño horizontal (thumbnails): 1344×768

---

## Sistema de perfiles de tono (nuevo)

```python
# tone_profile.py — single source of truth
def get_tone_profile_for_category(category: str) -> str:
    cat = (category or "").strip().lower()
    if any(k in cat for k in ("misterio", "conspiraci", "paranormal", "ovni")):
        return "mystery"
    if any(k in cat for k in ("natural", "desastre", "extremo", "catastrof")):
        return "dramatic_factual"
    if any(k in cat for k in ("historia", "documental", "ciencia", "tecnolog", "actualidad")):
        return "documentary"
    return "documentary"
```

| Categoría GUI | Perfil | Comportamiento |
|---|---|---|
| Historia militar/guerras, Historia antigua/civilizaciones, Documentales, Ciencia/Tec actual, Actualidad científica | `documentary` | Historiador serio. Prohibido inventar maldiciones, OVNIs, conspiraciones |
| Eventos naturales extremos | `dramatic_factual` | Tensión cinematográfica + 100% factual, sin paranormal |
| Misterios con datos, Conspiraciones verificables | `mystery` | Tono envolvente, "¿y si...?", framing especulativo permitido si está documentado |

---

## Validación de longitud de guion (nuevo)

Para Shorts (≤180s):
- Banda objetivo: `[duration × 2.0, duration × 2.75]` palabras (factor 2.5 medio)
- Mínimo aceptable: 80% del target
- Máximo aceptable: 110% del target
- Si fuera de banda → retry con expansión/compresión
- Máximo 2 retries, mejora monotónica (si el reintento no acerca a la banda, se descarta)

Para 60s: banda **120–165 palabras**, target ideal 150.

---

## Benchmarks de rendimiento

### RTX 3060 12GB ($0.043-0.057/hr)
- Schnell (4 steps): ~30s
- Dev (25 steps): ~101s

### Q RTX 5000 16GB ($0.04/hr)
- Schnell (4 steps): ~27s
- Dev (25 steps): ~55s

### Comparación de calidad Dev vs Schnell
Dev produce imágenes con mejor detalle en texturas, iluminación más natural/cinemática, y mejores proporciones anatómicas (especialmente rostros y manos). Para el canal @Stunning-Revelations (estilo documental cinematográfico oscuro), Dev es claramente superior.

---

## API Vast.ai — Endpoints útiles

```
GET    /api/v0/instances/           → lista todas las instancias (usar ESTE, no el individual)
PUT    /api/v0/instances/{id}/      → cambiar estado: {"state": "running"} o {"state": "stopped"}
DELETE /api/v0/instances/{id}/      → destruir instancia
GET    /api/v0/bundles/?q={json}    → buscar máquinas disponibles
PUT    /api/v0/asks/{offer_id}/     → crear instancia en una oferta
POST   /api/v0/ssh/                 → añadir SSH key a la cuenta (no propaga a instancias corriendo)
POST   /api/v0/instances/{id}/ssh/  → adjuntar SSH key directamente a una instancia
GET    /api/v0/ssh/                 → listar SSH keys de la cuenta
```
Header: `Authorization: Bearer {api_key}`

---

## Instancias destruidas (historial)
| ID | GPU | Motivo de destrucción |
|----|-----|----------------------|
| 37107457 | RTX 4090 | resources_unavailable |
| 37137898 | L40S | disco lleno (30GB) |
| 37186239 | RTX 3060 | resources_unavailable |
| 37207752 | RTX 4090 | imagen Docker incorrecta (pytorch genérico) |
| 37209273 | RTX 3060 | stuck en loading >20 min |
| 37210399 | RTX 3090 | stuck en created |
| 37211080 | RTX 4070 | CPU i5-3570K sin AVX2 (SIGILL) |
| 37222123 | Q RTX 5000 | resources_unavailable |
| 37224870 | Quadro GV100 | retries exceeded (host i7-10700K en Italia) |
| **37289130** | **RTX 3060** | **PENDIENTE de destruir — resources_unavailable (2026-05-22 ~16:30)** |
