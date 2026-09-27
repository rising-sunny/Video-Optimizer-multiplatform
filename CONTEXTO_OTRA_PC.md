# Contexto y setup para IA agéntica — otra PC

> **Para la IA que recibe esto:** este documento es autocontenido. Tu tarea es dejar
> el proyecto `Video-Optimizer-multiplatform` clonado y funcionando en ESTA PC
> (una PC distinta de la principal donde se hicieron los últimos cambios).
> Seguí las secciones en orden. Hay cosas que NO están en git (secretos, entorno
> virtual, junctions a Drive) y vas a tener que pedírselas al usuario o recrearlas.

---

## 0. Pedile esto al usuario ANTES de empezar

No están en el repo (a propósito). Si falta alguno, pará y pedíselo:

- [ ] **Secretos del `.env`**: `WHISPER_REMOTE_TOKEN` (de Whisper en el VPS),
      `GROQ_API_KEY`, `STABILITY_API_KEY`, credenciales OAuth de Google, claves VAST,
      y cualquier otra API key. El usuario las copia del `.env` de la PC principal.
- [ ] **Google Drive**: ¿está montado en esta PC? ¿En qué letra/ruta?
      (en la principal es `G:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform`).
- [ ] **SSH al VPS**: ¿`ssh root@5.78.125.169` entra sin password desde esta PC?
      (necesario para el túnel de Whisper). Si no, hay que autorizar la clave SSH.

**Nunca** inventes secretos ni los escribas en archivos versionados.

---

## 1. Qué es el proyecto (resumen)

App de escritorio **PyQt6** que genera videos cortos (Shorts/Reels) con IA:
storyboard → narración TTS → imágenes IA → ensamblaje con FFmpeg → subtítulos.
Repo privado: `https://github.com/rising-sunny/Video-Optimizer-multiplatform` (rama `main`).

---

## 2. Cambios recientes importantes (qué vas a encontrar en el repo)

El runtime se rehízo hace poco. **Esto es el estado actual:**

1. **La app corre en un venv local** (`.venv`, Python 3.11), NO en el viejo
   `python_portable` (que era un junction a Google Drive y fue eliminado).
   Los lanzadores `RUN.bat` / `INSTALL_DEPS.bat` ya apuntan al `.venv`.
2. **Whisper (transcripción de subtítulos) corre en un VPS remoto**, no local.
   Por eso el entorno local NO incluye `torch` ni `openai-whisper` (son pesados).
   Hay un `requirements_local.txt` liviano para esto.
3. Se sacó casi todo de Google Drive. Solo `projects/`, `daily_shorts/`,
   `auto_videos/` y `long_form/` siguen como **junctions** a Drive (por su peso).
4. Mejoras de código recientes ya en el repo: dedup de títulos YouTube en `daily_short_pipeline.py`,
   `gc.collect()` en `video_export_manager.py` (evita MemoryError), logging en
   `auto_video_generator_v2.py`.

Más detalle del worker de Whisper está en el código y en los comentarios de
`_whisper_subprocess_worker.py` y `RUN.bat`.

---

## 3. Requisitos previos en esta PC

- **Python 3.11** con el launcher `py`. Verificá: `py -3.11 --version` → `3.11.x`.
  Si falta: https://www.python.org/downloads/release/python-3110/
  (marcá "Add to PATH" y "py launcher").
- **FFmpeg** en el PATH. Verificá: `ffmpeg -version`.
- **Git** con acceso al repo privado.
- **Google Drive** (Drive File Stream) montado, si se usan las carpetas compartidas.

---

## 4. Clonar el repo

```bat
git clone https://github.com/rising-sunny/Video-Optimizer-multiplatform.git C:\dev\Video-Optimizer-multiplatform
cd C:\dev\Video-Optimizer-multiplatform
```
(Si ya existe la carpeta, en vez de clonar: `cd` y `git pull`.)

---

## 5. Crear el venv e instalar dependencias

```bat
INSTALL_DEPS.bat
```

Crea `.venv\` (Python 3.11) e instala `requirements_local.txt`: deps **livianas, sin
torch/whisper** (~1 GB). El `.venv` NO está en git; cada PC arma el suyo.

> Si alguna vez se quiere Whisper 100% local en esta PC (sin VPS), instalar el
> `requirements.txt` completo en el venv (pesa mucho más: torch).

---

## 6. Configurar el `.env` (secretos — NO van en git)

Crear/editar `C:\dev\Video-Optimizer-multiplatform\.env` con (además de las demás
API keys que dé el usuario):

```ini
# Whisper remoto (VPS) via tunel SSH
WHISPER_REMOTE_URL=http://127.0.0.1:8771
WHISPER_REMOTE_TOKEN=<pedirselo al usuario / copiar del .env de la PC principal>
WHISPER_REMOTE_MODEL=base
WHISPER_REMOTE_STRICT=1
```

> El `WHISPER_REMOTE_TOKEN` es secreto: no lo pongas en git ni en docs. Vive en el
> `.env` de la PC principal y en el VPS (`/opt/whisper-svc/.env`).
> Para los borradores de TikTok también hacen falta `TIKTOK_CLIENT_KEY`,
> `TIKTOK_CLIENT_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` y `token_tiktok.json`
> (o reconectar con `.venv\Scripts\python.exe tiktok_uploader.py --auth`).

---

## 7. Carpetas en Google Drive (junctions)

`projects/`, `daily_shorts/`, `auto_videos/` se comparten vía Drive (no son locales)
y se enlazan con *junctions*. Así ambas PCs ven los mismos proyectos.

Si Drive está montado en `G:` con la misma ruta que la PC principal, en `cmd` (NO
PowerShell), con la carpeta destino aún inexistente:

```bat
cd C:\dev\Video-Optimizer-multiplatform
mklink /J projects      "G:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform\projects"
mklink /J daily_shorts  "G:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform\daily_shorts"
mklink /J auto_videos   "G:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform\auto_videos"
mklink /J long_form     "G:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform\long_form"
```

> Ajustá la ruta si Drive usa otra letra. Si una carpeta ya existe (no vacía),
> movela antes. El resto de carpetas son locales y las crea la app sola.

---

## 8. (Opcional pero recomendado) Túnel SSH para subtítulos word-level

Whisper corre en el VPS `5.78.125.169` (servicio `whisper-svc`, escucha en
`127.0.0.1:8771`). Para alcanzarlo se usa un túnel SSH.

**Requisito:** `ssh root@5.78.125.169` debe entrar sin password desde esta PC. Si no,
copiar la clave pública de esta PC a `~/.ssh/authorized_keys` del VPS.

Antes de generar videos, abrir (y dejar abierta) la ventana:
```bat
start_whisper_tunnel.bat
```

Verificar que llega: `curl http://127.0.0.1:8771/health` → `{"ok":true,...}`.

> Si el túnel está caído y `WHISPER_REMOTE_STRICT=1`, los subtítulos caen a timing
> por segmento (menos preciso) pero la app NO se cae.

---

## 9. Correr la app

```bat
RUN.bat
```
Arranca con el venv local y `video_optimizer_pyqt6.py`.

---

## 10. Gotchas / advertencias importantes

- **NO uses** el Python 3.11 **global** del sistema (`%LOCALAPPDATA%\Programs\Python\
  Python311`) si en esta PC también está corrupto como en la principal. Usá SIEMPRE
  el `.venv`. (En la PC principal el global tenía ~9 paquetes a medio instalar por un
  disco lleno; por eso se migró a venv.)
- **No importes torch/whisper en local** — son pesados y la PC principal tiene poca
  RAM. La transcripción va al VPS.
- **Borrar un junction:** usá `[System.IO.Directory]::Delete($path, $false)` (borra
  solo el link). `Remove-Item`/`rmdir` puede ser bloqueado o borrar el target real.
- **No commitees secretos** (el `.env` está gitignored; mantenelo así).
- **Convención de guardado:** cuando el usuario diga "guardá"/"subí a git", hacer
  `git add` + `commit` (mensaje descriptivo) + `git push origin main`.

---

## 11. Checklist final

- [ ] `py -3.11 --version` OK
- [ ] Repo clonado en `C:\dev\Video-Optimizer-multiplatform`
- [ ] `INSTALL_DEPS.bat` corrido → `.venv\` creado sin errores (`pip check` limpio)
- [ ] `.env` con `WHISPER_REMOTE_*` + demás API keys
- [ ] Junctions de Drive creados (si se usan proyectos compartidos)
- [ ] `start_whisper_tunnel.bat` conecta y `/health` responde
- [ ] `RUN.bat` abre la app
