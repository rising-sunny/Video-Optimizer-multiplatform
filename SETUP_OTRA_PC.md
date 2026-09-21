# Setup en otra PC

Pasos para dejar el proyecto andando en una PC nueva (o sincronizar una existente).

> **Por qué hay pasos manuales:** git trae el *código*, pero el entorno virtual
> (`.venv/`) y el archivo `.env` están en `.gitignore` a propósito (el venv es
> pesado y específico de cada PC; el `.env` tiene secretos). Además los *junctions*
> a Google Drive no los versiona git. Esos hay que recrearlos localmente.

---

## 📋 PARA LA IA AGÉNTICA (Claude Code, etc.)

Si una IA está ejecutando este setup, seguí los pasos 1→6 en orden. **Antes de
empezar, pedile al usuario estos datos que NO están en git y que vas a necesitar:**

- [ ] Valores secretos para el `.env`: `WHISPER_REMOTE_TOKEN`, `GROQ_API_KEY`,
      `STABILITY_API_KEY`, credenciales OAuth de Google, claves VAST, etc.
      (el usuario los copia del `.env` de la PC principal).
- [ ] ¿Google Drive está montado en esta PC? ¿En qué letra y ruta?
      (en la PC principal es `G:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform`).
- [ ] ¿El `ssh root@5.78.125.169` entra sin password desde esta PC?
      (necesario para el túnel Whisper; si no, hay que autorizar la clave SSH).

No inventes esos valores ni los pongas en archivos versionados. Si falta alguno,
pará y pedíselo al usuario.

---

## 1. Requisitos previos

- **Python 3.11** con el launcher `py`. Verificá: `py -3.11 --version` → `Python 3.11.x`.
  Si no está: https://www.python.org/downloads/release/python-3110/
  (marcá "Add python.exe to PATH" y el "py launcher" en el instalador).
- **FFmpeg** en el PATH (lo usa moviepy/pydub). Verificá: `ffmpeg -version`.
- **Git** con acceso al repo `rising-sunny/Video-Optimizer-multiplatform`.
- **Google Drive** (Drive File Stream) montado, si vas a usar las carpetas
  compartidas (`projects`, salidas de video).

---

## 2. Traer el código

Si la carpeta ya existe:
```bat
cd C:\dev\Video-Optimizer-multiplatform
git pull
```

Si es una PC nueva (clonar):
```bat
git clone https://github.com/rising-sunny/Video-Optimizer-multiplatform.git C:\dev\Video-Optimizer-multiplatform
cd C:\dev\Video-Optimizer-multiplatform
```

---

## 3. Crear el entorno virtual e instalar dependencias

```bat
INSTALL_DEPS.bat
```

Crea `.venv\` (Python 3.11) e instala `requirements_local.txt`: deps **livianas,
sin torch ni openai-whisper** (~1 GB). La transcripción Whisper NO corre acá —
corre en el VPS (paso 5).

> Para Whisper 100% local en esta PC (sin VPS), instalá `requirements.txt` completo
> en el venv (pesa mucho más: torch).

---

## 4. Configurar el `.env`

El `.env` no viaja por git. Creá/editá `C:\dev\Video-Optimizer-multiplatform\.env`
con (además de tus otras claves de API):

```ini
# Whisper remoto (VPS) via tunel SSH
WHISPER_REMOTE_URL=http://127.0.0.1:8771
WHISPER_REMOTE_TOKEN=<copialo del .env de la PC principal>
WHISPER_REMOTE_MODEL=base
WHISPER_REMOTE_STRICT=1
```

> El `WHISPER_REMOTE_TOKEN` es un secreto: NO lo pongas en git ni en docs. Está en
> el `.env` de la PC principal (`grep WHISPER_REMOTE_TOKEN .env`) y, en el VPS, en
> `/opt/whisper-svc/.env`. Copialo de ahí.
> Las demás claves (`GROQ_API_KEY`, `STABILITY_API_KEY`, OAuth Google, VAST…)
> también copialas del `.env` de la PC principal — tampoco están en git.

---

## 5. Carpetas en Google Drive (junctions)

Por peso, estas carpetas se comparten vía Drive (NO son locales) y se enlazan con
*junctions*. Compartirlas por Drive hace que ambas PCs vean los mismos proyectos.

Si Drive está montado en `G:` con la misma ruta que la PC principal, recreá los
junctions (en `cmd`, NO PowerShell; la carpeta destino debe NO existir aún):

```bat
cd C:\dev\Video-Optimizer-multiplatform
mklink /J projects      "G:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform\projects"
mklink /J daily_shorts  "G:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform\daily_shorts"
mklink /J auto_videos   "G:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform\auto_videos"
mklink /J long_form     "G:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform\long_form"
```

> Si la letra/ruta de Drive es distinta en esta PC, ajustá el destino. Si una
> carpeta ya existe (no vacía), movela/borrala antes de crear el junction.
> El resto de carpetas (`project_media`, `thumbnails*`, etc.) son locales y las
> crea la app sola cuando hace falta.

---

## 6. (Opcional) Túnel SSH para subtítulos con timing por palabra

Whisper corre en el VPS `5.78.125.169` (`whisper-svc`, escucha en `127.0.0.1:8771`).
Para alcanzarlo se usa un túnel SSH.

**Requisito:** que `ssh root@5.78.125.169` entre sin password desde esta PC. Si no,
copiá la clave pública de esta PC al `~/.ssh/authorized_keys` del VPS.

Antes de generar videos, abrí (y dejá abierta) la ventana:
```bat
start_whisper_tunnel.bat
```

> Si el túnel está caído y `WHISPER_REMOTE_STRICT=1`, los subtítulos caen a timing
> por segmento (menos preciso) pero la app NO se cae.

---

## 7. Correr la app

```bat
RUN.bat
```

Arranca con el venv local. Listo.

---

## Notas

- **No uses** el `python_portable` viejo ni el Python 3.11 global de la PC principal
  (estaba corrupto). Siempre el `.venv`.
- Detalle técnico del servicio Whisper del VPS: memoria del proyecto
  (`project_whisper_vps.md`).
