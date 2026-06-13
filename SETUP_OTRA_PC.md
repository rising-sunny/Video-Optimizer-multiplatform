# Setup en otra PC

Pasos para dejar el proyecto andando en una PC nueva (o sincronizar una existente)
después de un `git pull`.

> **Por qué hay pasos manuales:** git trae el *código*, pero el entorno virtual
> (`.venv/`) y el archivo `.env` están en `.gitignore` a propósito (el venv es
> pesado y específico de cada PC; el `.env` tiene secretos). Esos dos hay que
> recrearlos localmente.

---

## 1. Requisitos previos

- **Python 3.11** instalado, con el launcher `py`.
  Verificá con: `py -3.11 --version` → debe decir `Python 3.11.x`.
  Si no está: https://www.python.org/downloads/release/python-3110/
  (marcá "Add python.exe to PATH" / "py launcher" en el instalador).
- **FFmpeg** en el PATH (lo usa moviepy/pydub).
- **Git** configurado con acceso al repo `rising-sunny/Video-Optimizer-multiplatform`.

---

## 2. Traer el código

```bat
cd C:\dev\Video-Optimizer-multiplatform
git pull
```

---

## 3. Crear el entorno virtual e instalar dependencias

```bat
INSTALL_DEPS.bat
```

Esto crea `.venv\` (Python 3.11) e instala `requirements_local.txt`: las
dependencias **livianas, sin torch ni openai-whisper** (~1 GB). La transcripción
Whisper NO corre en esta PC — corre en el VPS (ver paso 5).

> Si alguna vez querés Whisper 100% local en esta PC (sin depender del VPS),
> instalá el `requirements.txt` completo en el venv. Pesa mucho más (torch).

---

## 4. Configurar el `.env`

El `.env` no viaja por git. Creá/editá `C:\dev\Video-Optimizer-multiplatform\.env`
y asegurate de que tenga este bloque (además de tus otras claves de API):

```ini
# Whisper remoto (VPS) via tunel SSH
WHISPER_REMOTE_URL=http://127.0.0.1:8771
WHISPER_REMOTE_TOKEN=<copialo del .env de la PC principal>
WHISPER_REMOTE_MODEL=base
WHISPER_REMOTE_STRICT=1
```

> El `WHISPER_REMOTE_TOKEN` es un secreto: NO lo pongas en git ni lo pegues en
> docs. Está en el `.env` de la PC principal (`grep WHISPER_REMOTE_TOKEN .env`) y,
> en el VPS, en `/opt/whisper-svc/.env`. Copialo de ahí.

> El resto de las claves (`GROQ_API_KEY`, `STABILITY_API_KEY`, OAuth de Google,
> VAST, etc.) copialas del `.env` de la PC principal — tampoco están en git.

---

## 5. (Opcional) Túnel SSH para subtítulos con timing por palabra

La transcripción Whisper corre en el VPS `5.78.125.169` (servicio `whisper-svc`,
escucha en `127.0.0.1:8771`). Para alcanzarlo desde esta PC se usa un túnel SSH.

**Requisito:** que la clave SSH de esta PC esté autorizada en el VPS
(`ssh root@5.78.125.169` debe entrar sin pedir password). Si no, copiá la clave
pública de esta PC al `~/.ssh/authorized_keys` del VPS.

Luego, antes de generar videos:

```bat
start_whisper_tunnel.bat
```

Dejá esa ventana abierta. Mapea `local 127.0.0.1:8771 -> VPS 127.0.0.1:8771` y
se reconecta solo si se cae.

> Si el túnel está caído y `WHISPER_REMOTE_STRICT=1`, los subtítulos caen a timing
> por segmento (menos preciso) pero **la app NO se cae**.

---

## 6. Correr la app

```bat
RUN.bat
```

Arranca con el venv local. Listo.

---

## Notas

- **Carpetas en Drive:** `projects/`, `daily_shorts/`, `auto_videos/` siguen como
  junctions a Google Drive (por peso). El resto es local. Si esta PC no tiene esos
  junctions armados, replicá el setup de junctions de la PC principal o ajustá según
  tu Drive. (git no versiona junctions.)
- **No uses el `python_portable`** viejo ni el Python 3.11 global de la PC principal
  (estaba corrupto). Siempre el `.venv`.
- Detalle técnico completo del servicio Whisper del VPS: ver la memoria del proyecto
  (`project_whisper_vps.md`).
