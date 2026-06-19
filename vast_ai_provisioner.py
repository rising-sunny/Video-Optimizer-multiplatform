"""Automated provisioning of a fresh Vast.ai ComfyUI instance.

When the configured instance dies (`resources_unavailable`, host pulled, etc.)
this module can rent a new machine, install ComfyUI + FLUX, and rewrite `.env`
so the app keeps working without manual intervention.

Design notes
------------
* **Pure logic is separated from I/O** so it can be unit-tested offline without
  spending money: ``cpu_supports_avx2``, ``rank_offers``, ``update_env_file`` and
  ``read_ssh_pubkey`` take plain data and have no network side effects.
* **Live operations** (search/create/start/ssh/download) are grouped in the
  ``VastProvisioner`` class and only run when explicitly invoked.
* Creating an instance **costs money**, so the caller must opt in. The manager
  wires this behind ``VAST_AUTO_FAILOVER`` (default OFF).
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import requests

PROJECT_DIR = Path(__file__).resolve().parent

DEFAULT_IMAGE = "vastai/comfy:v0.20.1-cuda-12.9-py312"
DEFAULT_DISK_GB = 70
DEFAULT_MIN_VRAM_MB = 12000
DEFAULT_API_BASE = "https://console.vast.ai/api/v0"

# Minimum GPU compute capability (x100) the ComfyUI Docker image's PyTorch build
# supports. The image ships PyTorch cu128, which is compiled ONLY for Turing (7.5)
# and newer. Older GPUs raise at sample time:
#   "CUDA error: no kernel image is available for execution on the device".
# Pascal (6.0/6.1: Tesla P100, Titan Xp, GTX 10xx) and older are excluded.
# Vast.ai exposes this as the integer `compute_cap` field (750 = sm_75, 860 = sm_86).
DEFAULT_MIN_COMPUTE_CAP = 750

FLUX_MODELS = {
    "flux1-schnell-fp8.safetensors":
        "https://huggingface.co/Comfy-Org/flux1-schnell/resolve/main/flux1-schnell-fp8.safetensors",
    "flux1-dev-fp8.safetensors":
        "https://huggingface.co/Comfy-Org/flux1-dev/resolve/main/flux1-dev-fp8.safetensors",
}

# Public key used this account historically (fallback when no local key is found).
_FALLBACK_PUBKEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIL7XJOfl8QU2y74C8S8gyzA51aDW04dML6+Wrvb7aOXY windsurf"
)


# --------------------------------------------------------------------------- #
# Pure logic (no network) — safe to unit-test                                 #
# --------------------------------------------------------------------------- #

def cpu_supports_avx2(cpu_name: str) -> bool:
    """Best-effort detection of AVX2 support from a Vast.ai ``cpu_name`` string.

    AVX2 shipped with Intel Haswell (Core 4th gen, 2013) and AMD Zen/Excavator.
    The ComfyUI Docker image crashes with SIGILL on CPUs without it, so we must
    filter offers up front.
    """
    name = (cpu_name or "").strip().lower()
    if not name:
        return False

    # AMD: every Ryzen / EPYC / Threadripper has AVX2. Old FX/Opteron/Phenom don't.
    if any(k in name for k in ("ryzen", "epyc", "threadripper")):
        return True
    if any(k in name for k in ("opteron", "fx-", "phenom", "athlon", "a-series")):
        return False

    # Intel Xeon
    if "xeon" in name:
        if any(k in name for k in ("gold", "silver", "platinum", "bronze", "w-")):
            return True  # Skylake-SP and newer — all AVX2
        m = re.search(r"e[357]-?\d+\s*v(\d)", name)  # E3/E5/E7 vN: v3+ = Haswell+
        if m:
            return int(m.group(1)) >= 3
        return False  # unknown / pre-v3 Xeon — reject to be safe

    # Intel "Core Ultra" (Meteor Lake and newer) — definitely AVX2
    if "core ultra" in name or "ultra " in name:
        return True

    # Intel Core iX-NNNN — derive the generation from the model number
    m = re.search(r"i[3579][- ]?(\d{3,5})", name)
    if m:
        model = m.group(1)
        if len(model) == 3:
            return False           # 1st gen (Nehalem/Westmere) — no AVX2
        if len(model) == 4:
            gen = int(model[0])    # 2=Sandy, 3=Ivy, 4=Haswell, ...
        else:
            gen = int(model[:2])   # 10xxx, 11xxx, ...
        return gen >= 4            # Haswell (4th gen) introduced AVX2

    return False  # unknown CPU — reject rather than risk a SIGILL crash


def rank_offers(
    offers: list[dict[str, Any]],
    *,
    min_vram_mb: int = DEFAULT_MIN_VRAM_MB,
    min_disk_gb: int = DEFAULT_DISK_GB,
    require_avx2: bool = True,
    min_compute_cap: int = DEFAULT_MIN_COMPUTE_CAP,
) -> list[dict[str, Any]]:
    """Filter offers to viable machines and sort cheapest-first.

    Viable = enough VRAM, enough disk, rentable, AVX2-capable CPU (if required),
    and a GPU new enough for the image's PyTorch build (compute_cap >= threshold).
    """
    viable = []
    for o in offers:
        if not o.get("rentable", True):
            continue
        if (o.get("gpu_ram") or 0) < min_vram_mb:
            continue
        if (o.get("disk_space") or 0) < min_disk_gb:
            continue
        # Avoid extremely slow downloads for the large ComfyUI Docker image
        if (o.get("inet_down") or 0) < 100:
            continue
        # GPU too old for the cu128 PyTorch build -> would fail at sample time with
        # "no kernel image is available for execution on the device" (e.g. Pascal).
        if (o.get("compute_cap") or 0) < min_compute_cap:
            continue
        if require_avx2 and not cpu_supports_avx2(o.get("cpu_name", "")):
            continue
        viable.append(o)
    viable.sort(key=lambda o: (o.get("dph_total") or 9999, -(o.get("inet_down") or 0)))
    return viable


def update_env_file(env_path: Path, updates: dict[str, str]) -> None:
    """Rewrite ``key=value`` lines in a .env file, preserving comments/order.

    Keys present in the file are replaced in place; missing keys are appended.
    Never raises on a missing file — it creates one.
    """
    env_path = Path(env_path)
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8", errors="ignore").splitlines()

    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
                continue
        out.append(line)

    for key, value in remaining.items():
        out.append(f"{key}={value}")

    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def read_ssh_pubkey(explicit_path: Optional[str] = None) -> str:
    """Return an SSH public key string, searching common locations.

    Order: explicit path / ``VAST_SSH_PUBKEY`` env / ~/.ssh/id_ed25519.pub /
    id_rsa.pub, falling back to the historical account key.
    """
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path))
    env_path = os.getenv("VAST_SSH_PUBKEY")
    if env_path:
        candidates.append(Path(env_path))
    ssh_dir = Path.home() / ".ssh"
    candidates.extend([ssh_dir / "id_ed25519.pub", ssh_dir / "id_rsa.pub"])

    for path in candidates:
        try:
            if path.exists():
                content = path.read_text(encoding="utf-8", errors="ignore").strip()
                if content.startswith("ssh-"):
                    return content
        except Exception:
            continue
    return _FALLBACK_PUBKEY


# --------------------------------------------------------------------------- #
# Live provisioning                                                           #
# --------------------------------------------------------------------------- #

@dataclass
class ProvisionResult:
    instance_id: int
    ssh_host: str
    ssh_port: int
    gpu_name: str
    dph_total: float


class VastProvisioner:
    """Performs the live Vast.ai provisioning steps. Each method does one thing."""

    def __init__(
        self,
        api_key: str,
        *,
        log: Optional[Callable[[str], None]] = None,
        api_base_url: str = DEFAULT_API_BASE,
        ssh_user: str = "root",
        request_timeout: int = 30,
    ) -> None:
        if not api_key:
            raise ValueError("api_key requerido para aprovisionar Vast.ai")
        self.api_key = api_key
        self.api_base_url = api_base_url.rstrip("/")
        self.ssh_user = ssh_user
        self.request_timeout = request_timeout
        self._log = log or (lambda m: print(m))

    # -- API helpers ------------------------------------------------------- #
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _http(self, method: str, url: str, *, retries: int = 4, backoff: float = 2.0, **kwargs):
        """HTTP request with retry on transient connection errors.

        Vast.ai's API occasionally closes the connection mid-request
        (RemoteDisconnected / Connection aborted). Those are transient, so we
        retry with exponential backoff instead of aborting the whole provision.
        """
        kwargs.setdefault("timeout", self.request_timeout)
        kwargs.setdefault("headers", self._headers())
        last_exc = None
        for attempt in range(retries):
            try:
                return requests.request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt < retries - 1:
                    wait = backoff * (2 ** attempt)
                    self._log(f"[Provisioner] red inestable ({type(exc).__name__}); "
                             f"reintento {attempt + 1}/{retries - 1} en {wait:.0f}s")
                    time.sleep(wait)
        raise last_exc

    def search_offers(self, *, min_vram_mb: int = DEFAULT_MIN_VRAM_MB,
                      min_disk_gb: int = DEFAULT_DISK_GB, limit: int = 30) -> list[dict[str, Any]]:
        q = json.dumps({
            "gpu_ram": {"gte": min_vram_mb},
            "disk_space": {"gte": min_disk_gb},
            "rentable": {"eq": True},
            "verified": {"eq": True},
            "type": "on-demand",
            "order": [["dph_total", "asc"]],
            "limit": limit,
        })
        r = self._http("GET", f"{self.api_base_url}/bundles/", params={"q": q})
        r.raise_for_status()
        return r.json().get("offers", [])

    def create_instance(self, offer_id: int, *, image: str = DEFAULT_IMAGE,
                       disk_gb: int = DEFAULT_DISK_GB) -> int:
        r = self._http(
            "PUT",
            f"{self.api_base_url}/asks/{offer_id}/",
            json={"client_id": "me", "image": image, "disk": disk_gb, "onstart": "entrypoint.sh"},
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success") or not data.get("new_contract"):
            raise RuntimeError(f"Vast.ai no creo la instancia: {data}")
        return int(data["new_contract"])

    def start_and_wait(self, instance_id: int, *, timeout_s: int = 1200,
                      poll_s: int = 10) -> dict[str, Any]:
        requests.put(f"{self.api_base_url}/instances/{instance_id}/",
                    headers=self._headers(), json={"state": "running"},
                    timeout=self.request_timeout)
        deadline = time.time() + timeout_s
        last = None
        while time.time() < deadline:
            time.sleep(poll_s)
            try:
                r = requests.get(f"{self.api_base_url}/instances/", headers=self._headers(),
                                timeout=self.request_timeout)
                inst = next((i for i in r.json().get("instances", []) if i.get("id") == instance_id), None)
            except Exception:
                continue
            if not inst:
                continue
            status = inst.get("actual_status")
            if status != last:
                self._log(f"[Provisioner] instancia {instance_id} status={status}")
                last = status
            if status == "running" and inst.get("ssh_host"):
                return inst
            if status in ("exited", "error") and inst.get("intended_status") == "stopped":
                raise RuntimeError(f"La instancia {instance_id} no arranco (status={status})")
        raise TimeoutError(f"Timeout esperando que la instancia {instance_id} arranque")

    def attach_ssh_key(self, instance_id: int, pubkey: str) -> None:
        try:
            requests.post(f"{self.api_base_url}/instances/{instance_id}/ssh/",
                         headers=self._headers(), json={"ssh_key": pubkey},
                         timeout=self.request_timeout)
        except Exception as exc:
            self._log(f"[Provisioner] aviso: no se pudo adjuntar SSH key: {exc}")

    def destroy_instance(self, instance_id: int) -> None:
        try:
            requests.delete(f"{self.api_base_url}/instances/{instance_id}/",
                           headers=self._headers(), timeout=self.request_timeout)
            self._log(f"[Provisioner] instancia {instance_id} destruida")
        except Exception as exc:
            self._log(f"[Provisioner] aviso: no se pudo destruir {instance_id}: {exc}")

    # -- SSH helpers ------------------------------------------------------- #
    def _ssh(self, host: str, port: int, command: str, *, timeout_s: int = 60) -> tuple[int, str]:
        cmd = [
            "ssh", "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=15", "-p", str(port),
            f"{self.ssh_user}@{host}", command,
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if platform.system().lower().startswith("win") else 0
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=timeout_s, creationflags=creationflags)
            return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            return 124, "ssh timeout"

    def wait_for_ssh(self, host: str, port: int, *, timeout_s: int = 180) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            code, _ = self._ssh(host, port, "echo ok", timeout_s=20)
            if code == 0:
                return
            time.sleep(8)
        raise TimeoutError(f"SSH no respondio en {host}:{port}")

    def configure_comfyui(self, host: str, port: int) -> None:
        # Enable ComfyUI in the supervisor portal (regex needs a non-'#' first char).
        self._ssh(host, port, "echo '- ComfyUI' > /etc/portal.yaml && supervisorctl restart comfyui",
                 timeout_s=60)

    def download_models(self, host: str, port: int, *, timeout_s: int = 1200) -> None:
        for fname, url in FLUX_MODELS.items():
            self._log(f"[Provisioner] descargando {fname} ...")
            code, out = self._ssh(
                host, port,
                f"cd /workspace/ComfyUI/models/checkpoints && curl -L -sS -o {fname} '{url}'",
                timeout_s=timeout_s,
            )
            if code != 0:
                raise RuntimeError(f"Fallo descargando {fname}: {out[-200:]}")

    def wait_for_comfyui_http(self, host: str, port: int, *, timeout_s: int = 180) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            code, out = self._ssh(
                host, port,
                "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18188/system_stats",
                timeout_s=20,
            )
            if code == 0 and "200" in out:
                return
            time.sleep(6)
        raise TimeoutError("ComfyUI no respondio por HTTP tras el aprovisionamiento")

    # -- Orchestrator ------------------------------------------------------ #
    def provision(self, *, min_vram_mb: int = DEFAULT_MIN_VRAM_MB,
                 min_disk_gb: int = DEFAULT_DISK_GB,
                 download_flux: bool = True) -> ProvisionResult:
        """Full pipeline: pick offer -> create -> start -> ssh -> models -> verify."""
        self._log("[Provisioner] buscando oferta verificada con AVX2 ...")
        offers = rank_offers(self.search_offers(min_vram_mb=min_vram_mb, min_disk_gb=min_disk_gb),
                            min_vram_mb=min_vram_mb, min_disk_gb=min_disk_gb)
        if not offers:
            raise RuntimeError("No hay ofertas viables (VRAM/disco/AVX2/Internet) ahora mismo")
        
        last_error = None
        for offer in offers[:10]:
            self._log(f"[Provisioner] elegida: {offer.get('gpu_name')} "
                     f"${offer.get('dph_total'):.4f}/hr CPU={offer.get('cpu_name')}")
            instance_id = None


            try:
                instance_id = self.create_instance(int(offer["id"]), disk_gb=max(min_disk_gb, DEFAULT_DISK_GB))
                self._log(f"[Provisioner] instancia creada: {instance_id}")

                self.attach_ssh_key(instance_id, read_ssh_pubkey())
                # Timeout un poco mas corto para aprovisionamiento inicial (15 min en vez de 20)
                inst = self.start_and_wait(instance_id, timeout_s=900)
                host = str(inst.get("ssh_host"))
                sport = int(inst.get("ssh_port"))
                self.wait_for_ssh(host, sport)
                self.configure_comfyui(host, sport)
                if download_flux:
                    self.download_models(host, sport)
                self.wait_for_comfyui_http(host, sport)
                
                self._log(f"[Provisioner] LISTO: {host}:{sport} ({offer.get('gpu_name')})")
                return ProvisionResult(
                    instance_id=instance_id, ssh_host=host, ssh_port=sport,
                    gpu_name=str(offer.get("gpu_name") or "?"),
                    dph_total=float(offer.get("dph_total") or 0.0),
                )
            except Exception as e:
                self._log(f"[Provisioner] Fallo aprovisionando la oferta {offer.get('id')}: {e}")
                if instance_id is not None:
                    try:
                        self.destroy_instance(instance_id)
                    except:
                        pass
                last_error = e
                continue
                
        raise RuntimeError(f"Fallo aprovisionar tras probar multiples ofertas. Ultimo error: {last_error}")


__all__ = [
    "VastProvisioner", "ProvisionResult",
    "cpu_supports_avx2", "rank_offers", "update_env_file", "read_ssh_pubkey",
    "FLUX_MODELS", "DEFAULT_IMAGE",
]


def _main() -> int:
    """CLI: provision a fresh instance from scratch and write it into .env.

    Usage:
        python vast_ai_provisioner.py            # provision + update .env
        python vast_ai_provisioner.py --dry-run  # only list viable offers
        python vast_ai_provisioner.py --no-flux   # skip the 34GB model download
    """
    import argparse

    from env_loader import load_project_env
    load_project_env(PROJECT_DIR)

    parser = argparse.ArgumentParser(description="Aprovisionar instancia Vast.ai ComfyUI")
    parser.add_argument("--dry-run", action="store_true", help="Solo listar ofertas viables")
    parser.add_argument("--no-flux", action="store_true", help="No descargar modelos FLUX")
    parser.add_argument("--min-vram", type=int, default=DEFAULT_MIN_VRAM_MB, help="VRAM minima (MB)")
    parser.add_argument("--min-disk", type=int, default=DEFAULT_DISK_GB, help="Disco minimo (GB)")
    args = parser.parse_args()

    api_key = os.getenv("VAST_API_KEY")
    if not api_key:
        print("ERROR: VAST_API_KEY no esta en el entorno/.env")
        return 2

    prov = VastProvisioner(api_key, log=print)

    if args.dry_run:
        offers = rank_offers(
            prov.search_offers(min_vram_mb=args.min_vram, min_disk_gb=args.min_disk),
            min_vram_mb=args.min_vram, min_disk_gb=args.min_disk,
        )
        print(f"\n{len(offers)} ofertas viables (verificadas, AVX2, VRAM/disco OK):")
        for o in offers[:15]:
            print(f"  {o.get('gpu_name')} {(o.get('gpu_ram') or 0)//1024}GB | "
                  f"${o.get('dph_total'):.4f}/hr | CPU:{o.get('cpu_name')} | id={o.get('id')}")
        return 0

    try:
        result = prov.provision(min_vram_mb=args.min_vram, min_disk_gb=args.min_disk,
                               download_flux=not args.no_flux)
    except Exception as exc:
        print(f"\nFALLO el aprovisionamiento: {exc}")
        return 1

    update_env_file(PROJECT_DIR / ".env", {
        "VAST_INSTANCE_ID": str(result.instance_id),
        "VAST_SSH_HOST": result.ssh_host,
        "VAST_SSH_PORT": str(result.ssh_port),
    })
    print(f"\n.env actualizado. Instancia {result.instance_id} lista en "
          f"{result.ssh_host}:{result.ssh_port} ({result.gpu_name}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
