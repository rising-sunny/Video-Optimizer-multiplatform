"""Utilidades de la automatizacion de The Lost Atlas (Shorts diarios de quiz: geo / year / empire)."""
import fcntl, json, shutil, sys, datetime as dt
from pathlib import Path
ROOT = Path('/home/videoagent/tla-daily'); REPO = Path('/home/videoagent/Video-Optimizer-multiplatform')
sys.path.insert(0, str(REPO))
CHANNEL = 'the-lost-atlas'
STOP = ROOT / 'STOP'                 # interruptor: si existe, no se genera ni se publica nada
MIN_FREE_GB = 6.0
TEMPLATES = ['geo', 'year', 'empire']  # rotan por dia (ordinal % 3)
STATE = ROOT / 'state.json'          # entidades ya usadas (cooldown) para no repetir preguntas


class Skip(Exception):
    """El dia se salta (sin recuperar atrasos)."""


def today():
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def log(msg):
    line = f"{dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with open(ROOT / 'logs/tla.log', 'a') as f:
        f.write(line + '\n')


def atomic(path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp'); tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str)); tmp.replace(path)


def load(path, default=None):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else (default if default is not None else {})


def free_gb():
    return shutil.disk_usage('/home').free / 1e9


class Lock:
    def __enter__(self):
        self.f = open(ROOT / 'runtime/lock', 'w')
        try: fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise Skip('otra ejecucion en curso')
        return self
    def __exit__(self, *a): self.f.close()
