# Setup en otra PC

Pasos para dejar el proyecto andando en una PC nueva (o sincronizar una existente).

> **Por qué hay pasos manuales:** git trae el *código*, pero el entorno virtual
> (`.venv/`) y el archivo `.env` están en `.gitignore` a propósito (el venv es
> pesado y específico de cada PC; el `.env` tiene secretos). Además los *junctions*
> a Google Drive no los versiona git. Esos hay que recrearlos localmente.

---

## 📋 PARA LA IA AGÉNTICA (Claude Code, etc.)

Si una IA está ejecutando este setup, seguí los pasos 1→7 en orden. **Antes de
empezar, pedile al usuario estos datos que NO están en git y que vas a necesitar:**

- [ ] El `.env` completo de la PC principal (y el `.env.txt`, si existe): tiene las
      claves de todas las APIs (`WHISPER_REMOTE_TOKEN`, `GROQ_API_KEY`, fal.ai, Recraft,
      Gemini, Facebook/Instagram, Cloudinary, X, VAST…). Ver paso 4.
- [ ] Los archivos de YouTube `client_secrets.json` y `token.json` de la raíz del
      repo en la PC principal (NO van en el `.env`). Ver paso 4.
- [ ] La carpeta `transition_overlays/` de la PC principal (clips de transición y
      `swoosh.wav`; no está en git). Ver paso 5.
- [ ] ¿Google Drive está montado en esta PC? ¿En qué letra y ruta?
      (en la PC principal es `G:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform`).
- [ ] ¿El `ssh root@5.78.125.169` entra sin password desde esta PC?
      (necesario para el túnel Whisper y para publicar en Facebook/Instagram vía VPS;
      si no, hay que autorizar la clave SSH o apagar la publicación vía VPS, ver paso 6).

No inventes esos valores ni los pongas en archivos versionados. Si falta alguno,
pará y pedíselo al usuario.

---

## 1. Requisitos previos

- **Python 3.11** con el launcher `py`. Verificá: `py -3.11 --version` → `Python 3.11.x`.
  Si no está: https://www.python.org/downloads/release/python-3110/
  (marcá "Add python.exe to PATH" y el "py launcher" en el instalador).
- **FFmpeg** en el PATH (lo usa moviepy/pydub). Verificá: `ffmpeg -version`.
- **Git** con acceso al repo `rising-sunny/Video-Optimizer-multiplatform`.
- **Google Drive para escritorio** montado, si vas a usar las carpetas
  compartidas (`projects`, salidas de video).
- (Opcional) **Claude Code** instalado y con sesión iniciada: desde 2026-09-25 es el
  primer verificador de hechos del guion. Sin él, la app usa Gemini o Groq
  (`FACT_CHECK_CLAUDE=0` en el `.env` lo saca del todo).

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
corre en el VPS (paso 6).

> Para Whisper 100% local en esta PC (sin VPS), instalá `requirements.txt` completo
> en el venv (pesa mucho más: torch).

---

## 4. Configurar el `.env`

El `.env` no viaja por git. Copiá el `.env` completo de la PC principal a
`C:\dev\Video-Optimizer-multiplatform\`, y también el `.env.txt` si existe (la app
lee los dos, y la publicación vía VPS le manda el `.env.txt` al VPS). Tiene que
incluir el bloque de Whisper:

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
> Copiando el `.env` entero vienen también las demás claves (Groq, fal.ai, Recraft,
> Gemini, Facebook/Instagram, Cloudinary, X, VAST…); ninguna está en git.

**YouTube:** sus credenciales NO van en el `.env`. Son dos archivos en la raíz del
repo, `client_secrets.json` y `token.json` (también fuera de git): copialos de la PC
principal. Si solo copiás `client_secrets.json`, la primera vez que publiques se
abre el navegador para autorizar la cuenta.

---

## 5. Carpetas en Google Drive (junctions)

Por peso, estas carpetas se comparten vía Drive (NO son locales) y se enlazan con
*junctions*. Compartirlas por Drive hace que ambas PCs vean los mismos proyectos.

Si Drive está montado en `G:` con la misma ruta que la PC principal, recreá los
junctions (en `cmd`, NO PowerShell; la carpeta local no puede existir todavía).
En un clon nuevo, `daily_shorts` y `long_form` ya existen porque git trae archivos
adentro (el Channel Bible, `music_claims.json` y el proyecto Dyatlov): renombralas
primero. En la PC principal esas carpetas ya son los junctions, así que ese contenido
está en Drive. Si esta PC ya tiene los junctions, salteá este paso.

```bat
cd C:\dev\Video-Optimizer-multiplatform
ren daily_shorts daily_shorts_git
ren long_form    long_form_git
mklink /J projects      "G:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform\projects"
mklink /J daily_shorts  "G:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform\daily_shorts"
mklink /J auto_videos   "G:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform\auto_videos"
mklink /J long_form     "G:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform\long_form"
```

> Si la letra/ruta de Drive es distinta en esta PC, ajustá el destino. Cuando los
> junctions funcionen, podés borrar `daily_shorts_git` y `long_form_git` (son
> carpetas comunes del clon, no junctions).
> El resto de carpetas (`project_media`, `thumbnails*`, etc.) son locales y las
> crea la app sola cuando hace falta. **Excepción:** `transition_overlays/` (clips de
> la transición film burn y `swoosh.wav`) no la crea la app ni está en git: copiala
> a mano desde la PC principal. Sin ella, esa transición cae a un fundido y no
> suena el swoosh.
>
> **Sin Google Drive** en esta PC, salteá este paso: la app abre igual y guarda todo
> en carpetas locales, pero los proyectos no se comparten con la otra PC.

---

## 6. (Opcional) SSH al VPS: subtítulos con timing por palabra y publicación

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

**Publicar vía VPS:** si el `.env` tiene `VPS_SSH_HOST`, Facebook e Instagram se
suben a través del VPS, con la misma clave SSH. Si esta PC no entra al VPS, poné
`VPS_UPLOAD_ENABLED=0` en el `.env`: se suben desde esta PC, sin esperar ~40 s por
plataforma a que falle el SSH.

---

## 7. Correr la app

```bat
RUN.bat
```

Arranca con el venv local. Listo.

Para generar un Short por línea de comandos, sin abrir la app:
`GENERATE_SHORT.bat --topic "TEMA"` (usa el mismo `.venv`; sin `--topic` elige el
tema por tendencias).

---

## Notas

- **No uses** el `python_portable` viejo ni el Python 3.11 global de la PC principal
  (estaba corrupto). Siempre el `.venv`.
- Detalle técnico del Whisper remoto: la cabecera de `_whisper_subprocess_worker.py`
  (variables `WHISPER_REMOTE_*`) y `start_whisper_tunnel.bat`.
