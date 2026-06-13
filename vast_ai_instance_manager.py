"""Lifecycle manager for a Vast.ai ComfyUI instance.

This module keeps the Vast.ai-specific orchestration outside the image client:
start/stop the rented instance, open a local SSH tunnel, and wait for ComfyUI.
"""

from __future__ import annotations

import atexit
import os
import platform
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from env_loader import load_project_env


load_project_env()


# Vast.ai error codes that mean "this physical host cannot serve the request right
# now and retrying the same instance will not help" — we must fail fast instead of
# polling for minutes. The user then knows to pick another offer or top up credit.
_FATAL_START_ERRORS = {
    "resources_unavailable",
    "insufficient_credit",
    "no_such_instance",
    "instance_not_found",
}

# Subset of fatal errors where renting a *different* machine would actually help.
# (insufficient_credit is excluded: a new instance would fail the same way.)
_FAILOVER_ERRORS = {
    "resources_unavailable",
    "no_such_instance",
    "instance_not_found",
}

_PROJECT_DIR = Path(__file__).resolve().parent


class VastStartError(RuntimeError):
    """Raised when Vast.ai refuses to start the instance (e.g. resources_unavailable).

    Carries the machine-readable ``error_code`` so callers can decide whether to
    retry on another instance, prompt the user to add credit, etc.
    """

    def __init__(self, message: str, error_code: str = "") -> None:
        super().__init__(message)
        self.error_code = error_code

    @property
    def is_fatal(self) -> bool:
        return self.error_code in _FATAL_START_ERRORS


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(str(raw).strip()) if raw not in (None, "") else default
    except Exception:
        return default


def _redact(value: Optional[str]) -> str:
    if not value:
        return ""
    value = str(value)
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


@dataclass
class VastAiInstanceManager:
    """Start/stop Vast.ai and expose remote ComfyUI through localhost."""

    log_callback: Any = None
    api_key: Optional[str] = None
    instance_id: Optional[int] = None
    api_base_url: str = "https://console.vast.ai/api/v0"
    ssh_user: str = "root"
    ssh_host: Optional[str] = None
    ssh_port: Optional[int] = None
    remote_host: str = "127.0.0.1"
    remote_port: int = 18188
    local_host: str = "127.0.0.1"
    local_port: int = 8188
    start_timeout_seconds: int = 600
    health_timeout_seconds: int = 360
    request_timeout_seconds: int = 30
    auto_manage: bool = True
    auto_stop_on_exit: bool = True
    auto_failover: bool = False
    prefer_direct_ssh: bool = True
    shutdown_timeout_seconds: int = 10
    _tunnel_process: Optional[subprocess.Popen] = field(default=None, init=False, repr=False)
    _used_remote: bool = field(default=False, init=False, repr=False)
    _registered_atexit: bool = field(default=False, init=False, repr=False)
    _registered_qt: bool = field(default=False, init=False, repr=False)
    _shutdown_called: bool = field(default=False, init=False, repr=False)
    _fatal_start_error: Optional["VastStartError"] = field(default=None, init=False, repr=False)
    _failover_attempted: bool = field(default=False, init=False, repr=False)

    @classmethod
    def from_env(cls, log_callback=None) -> "VastAiInstanceManager":
        base_url = os.getenv("COMFYUI_BASE_URL") or "http://127.0.0.1:8188"
        parsed = urlparse(base_url)
        local_host = parsed.hostname or "127.0.0.1"
        local_port = parsed.port or (443 if parsed.scheme == "https" else 80)

        instance_id = None
        if os.getenv("VAST_INSTANCE_ID"):
            try:
                instance_id = int(os.getenv("VAST_INSTANCE_ID", "").strip())
            except Exception:
                instance_id = None

        return cls(
            log_callback=log_callback,
            api_key=os.getenv("VAST_API_KEY") or None,
            instance_id=instance_id,
            api_base_url=(os.getenv("VAST_API_BASE_URL") or "https://console.vast.ai/api/v0").rstrip("/"),
            ssh_user=os.getenv("VAST_SSH_USER") or "root",
            ssh_host=os.getenv("VAST_SSH_HOST") or None,
            ssh_port=_env_int("VAST_SSH_PORT", 0) or None,
            remote_host=os.getenv("COMFYUI_REMOTE_HOST") or "127.0.0.1",
            remote_port=_env_int("COMFYUI_REMOTE_PORT", 18188),
            local_host=local_host,
            local_port=local_port,
            start_timeout_seconds=_env_int("VAST_START_TIMEOUT_SECONDS", 600),
            health_timeout_seconds=_env_int("VAST_HEALTH_TIMEOUT_SECONDS", 360),
            request_timeout_seconds=_env_int("VAST_REQUEST_TIMEOUT_SECONDS", 30),
            auto_manage=_env_bool("VAST_AUTO_MANAGE", False),
            auto_stop_on_exit=_env_bool("VAST_AUTO_STOP_ON_EXIT", True),
            auto_failover=_env_bool("VAST_AUTO_FAILOVER", False),
            prefer_direct_ssh=_env_bool("VAST_PREFER_DIRECT_SSH", True),
            shutdown_timeout_seconds=_env_int("VAST_SHUTDOWN_TIMEOUT_SECONDS", 10),
        )

    @property
    def enabled(self) -> bool:
        has_ssh = bool(self.ssh_host and self.ssh_port)
        has_api = bool(self.api_key and self.instance_id)
        return bool(self.auto_manage and (has_api or has_ssh))

    @property
    def base_url(self) -> str:
        return f"http://{self.local_host}:{self.local_port}"

    def _log(self, message: str) -> None:
        self._log_to_file(message)
        if self.log_callback:
            try:
                self.log_callback(message)
                return
            except Exception:
                pass
        print(message)

    @staticmethod
    def _log_to_file(message: str) -> None:
        """Persist log to ~/.cache/video-optimizer/vast.log (best effort, never raises)."""
        try:
            log_dir = Path.home() / ".cache" / "video-optimizer"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "vast.log"
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            with log_file.open("a", encoding="utf-8") as fh:
                fh.write(f"[{ts}] {message}\n")
        except Exception:
            pass

    def _api_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("VAST_API_KEY no configurada")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _api_request(self, method: str, path: str, json_body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        url = f"{self.api_base_url}{path}"
        response = requests.request(
            method,
            url,
            headers=self._api_headers(),
            json=json_body,
            timeout=self.request_timeout_seconds,
        )
        response.raise_for_status()
        return response.json() if response.content else {}

    def get_instance(self) -> dict[str, Any]:
        if not self.instance_id:
            raise RuntimeError("VAST_INSTANCE_ID no configurado")
        payload = self._api_request("GET", f"/instances/{self.instance_id}/")
        instance = payload.get("instances") or payload.get("instance") or payload
        if not isinstance(instance, dict):
            raise RuntimeError(f"Respuesta inesperada de Vast.ai: {payload}")
        self._update_ssh_from_instance(instance)
        return instance

    def _set_instance_state(self, state: str) -> dict[str, Any]:
        if not self.instance_id:
            raise RuntimeError("VAST_INSTANCE_ID no configurado")
        return self._api_request("PUT", f"/instances/{self.instance_id}/", {"state": state})

    @staticmethod
    def _is_running(instance: dict[str, Any]) -> bool:
        states = {
            str(instance.get("actual_status") or "").lower(),
            str(instance.get("cur_state") or "").lower(),
            str(instance.get("intended_status") or "").lower(),
        }
        return "running" in states

    def _update_ssh_from_instance(self, instance: dict[str, Any]) -> None:
        if self.prefer_direct_ssh:
            public_ip = instance.get("public_ipaddr")
            ports = instance.get("ports") or {}
            ssh_bindings = ports.get("22/tcp") if isinstance(ports, dict) else None
            if public_ip and isinstance(ssh_bindings, list) and ssh_bindings:
                host_port = (ssh_bindings[0] or {}).get("HostPort")
                if host_port:
                    self.ssh_host = str(public_ip)
                    try:
                        self.ssh_port = int(host_port)
                    except Exception:
                        pass
                    return

        ssh_host = instance.get("ssh_host")
        ssh_port = instance.get("ssh_port")
        if ssh_host:
            self.ssh_host = str(ssh_host)
        if ssh_port:
            try:
                self.ssh_port = int(ssh_port)
            except Exception:
                pass

    def ensure_ready(self) -> bool:
        """Ensure the remote ComfyUI API is reachable on COMFYUI_BASE_URL."""
        if not self.enabled:
            return True

        self._used_remote = True
        self._register_atexit()

        if self.check_local_comfyui(timeout=3):
            return True

        # Circuit breaker: if a previous call hit a fatal start error (resources
        # unavailable, no credit...), don't hammer the API once per segment. Fail
        # immediately so a batch of N images aborts in seconds, not N x 10 minutes.
        if self._fatal_start_error is not None:
            raise self._fatal_start_error

        if self.api_key and self.instance_id:
            try:
                self.start_instance()
            except VastStartError as exc:
                # Auto-failover: if renting a different machine could help and the
                # user opted in, provision a fresh instance once and retry.
                if (exc.is_fatal and self.auto_failover
                        and exc.error_code in _FAILOVER_ERRORS
                        and self._attempt_failover()):
                    self.start_instance()  # new instance is already running -> quick
                elif exc.is_fatal:
                    self._fatal_start_error = exc
                    raise
                else:
                    raise
        elif not (self.ssh_host and self.ssh_port):
            raise RuntimeError("Vast.ai no tiene datos SSH disponibles para abrir el tunel")

        self.open_ssh_tunnel()
        self.wait_for_comfyui()
        return True

    def _attempt_failover(self) -> bool:
        """Provision a fresh instance to replace a dead one. Returns True on success.

        Only runs once per manager lifetime (``_failover_attempted`` guard) so a
        batch of images can't trigger a runaway of paid instances.
        """
        if self._failover_attempted:
            return False
        self._failover_attempted = True

        old_id = self.instance_id
        try:
            from vast_ai_provisioner import VastProvisioner, update_env_file

            self._log("[Vast.ai] Auto-failover: aprovisionando una instancia nueva...")
            provisioner = VastProvisioner(
                self.api_key,
                log=self._log,
                api_base_url=self.api_base_url,
                ssh_user=self.ssh_user,
            )
            result = provisioner.provision()
        except Exception as exc:
            self._log(f"[Vast.ai] Auto-failover fallo: {exc}")
            return False

        # Point this manager at the new instance.
        self.instance_id = result.instance_id
        self.ssh_host = result.ssh_host
        self.ssh_port = result.ssh_port

        # Persist so the next app run uses the new instance automatically.
        try:
            update_env_file(_PROJECT_DIR / ".env", {
                "VAST_INSTANCE_ID": str(result.instance_id),
                "VAST_SSH_HOST": result.ssh_host,
                "VAST_SSH_PORT": str(result.ssh_port),
            })
            self._log("[Vast.ai] .env actualizado con la instancia nueva")
        except Exception as exc:
            self._log(f"[Vast.ai] aviso: no se pudo actualizar .env: {exc}")

        # Destroy the dead instance so it stops accruing storage charges.
        if old_id and old_id != result.instance_id:
            try:
                provisioner.destroy_instance(old_id)
            except Exception:
                pass

        self._log(
            f"[Vast.ai] Failover OK -> instancia {result.instance_id} "
            f"({result.gpu_name}, ${result.dph_total:.4f}/hr)"
        )
        return True

    def reset_fatal_error(self) -> None:
        """Clear the circuit breaker so the next ensure_ready() retries the API.

        Call this after the user has fixed the underlying cause (added credit,
        pointed VAST_INSTANCE_ID at a fresh instance, etc.).
        """
        if self._fatal_start_error is not None:
            self._log("[Vast.ai] Reset del circuit breaker - se reintentara el arranque")
        self._fatal_start_error = None
        self._failover_attempted = False

    def start_instance(self) -> None:
        instance = self.get_instance()
        if self._is_running(instance):
            self._log("[Vast.ai] Instancia ya esta running")
            return

        self._log(f"[Vast.ai] Iniciando instancia {self.instance_id}...")
        response = self._set_instance_state("running")
        # Vast.ai returns HTTP 200 with {"success": false, "error": "..."} when it
        # cannot honour the request. raise_for_status() does NOT catch this, so we
        # must inspect the body or we will poll uselessly until start_timeout.
        if isinstance(response, dict) and response.get("success") is False:
            error_code = str(response.get("error") or "").strip()
            msg = str(response.get("msg") or response.get("error") or "desconocido").strip()
            self._log(f"[Vast.ai] Start rechazado: error={error_code or '?'} msg={msg}")
            if error_code in _FATAL_START_ERRORS:
                hint = {
                    "resources_unavailable": "El host fisico ya no esta disponible. Crea otra instancia en otra oferta.",
                    "insufficient_credit": "Saldo insuficiente en Vast.ai. Recarga credito para continuar.",
                    "no_such_instance": "La instancia ya no existe. Actualiza VAST_INSTANCE_ID.",
                    "instance_not_found": "La instancia ya no existe. Actualiza VAST_INSTANCE_ID.",
                }.get(error_code, "")
                raise VastStartError(
                    f"Vast.ai no pudo iniciar la instancia {self.instance_id}: {msg}"
                    + (f" - {hint}" if hint else ""),
                    error_code=error_code,
                )
            # Non-fatal "success: false" (e.g. transient queueing): warn and still poll,
            # the state change may be honoured shortly.

        deadline = time.time() + max(30, self.start_timeout_seconds)
        last_status = None

        while time.time() < deadline:
            time.sleep(5)
            instance = self.get_instance()
            last_status = (
                instance.get("actual_status")
                or instance.get("cur_state")
                or instance.get("intended_status")
            )
            if self._is_running(instance) and self.ssh_host and self.ssh_port:
                self._log(f"[Vast.ai] Instancia lista via SSH {self.ssh_host}:{self.ssh_port}")
                return
            self._log(f"[Vast.ai] Esperando instancia... status={last_status}")

        raise TimeoutError(f"Timeout esperando que Vast.ai inicie (ultimo status={last_status})")

    def stop_instance(self) -> None:
        self.close_ssh_tunnel()
        if not (self.api_key and self.instance_id):
            self._log("[Vast.ai] No se puede detener automaticamente: falta API key o instance id")
            return
        try:
            self._log(f"[Vast.ai] Deteniendo instancia {self.instance_id} para ahorrar creditos...")
            self._set_instance_state("stopped")
        except Exception as exc:
            self._log(f"[Vast.ai] No se pudo detener instancia: {exc}")

    def check_local_comfyui(self, timeout: int = 10) -> bool:
        try:
            response = requests.get(f"{self.base_url}/system_stats", timeout=timeout)
            return response.status_code == 200
        except Exception:
            return False

    def wait_for_comfyui(self) -> None:
        deadline = time.time() + max(30, self.health_timeout_seconds)
        while time.time() < deadline:
            if self.check_local_comfyui(timeout=10):
                self._log(f"[ComfyUI] Listo en {self.base_url}")
                return
            time.sleep(3)
        raise TimeoutError(f"Timeout esperando ComfyUI en {self.base_url}")

    def _local_port_in_use(self) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            return sock.connect_ex((self.local_host, self.local_port)) == 0

    def open_ssh_tunnel(self) -> None:
        if self.check_local_comfyui(timeout=3):
            return
        if self._tunnel_process and self._tunnel_process.poll() is None:
            return
        if not (self.ssh_host and self.ssh_port):
            raise RuntimeError("No hay ssh_host/ssh_port para abrir tunel Vast.ai")
        if self._local_port_in_use():
            raise RuntimeError(
                f"El puerto local {self.local_host}:{self.local_port} esta ocupado "
                "pero no responde como ComfyUI."
            )

        cmd = [
            "ssh",
            "-N",
            "-L",
            f"{self.local_port}:{self.remote_host}:{self.remote_port}",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-p",
            str(self.ssh_port),
            f"{self.ssh_user}@{self.ssh_host}",
        ]
        startupinfo = None
        creationflags = 0
        if platform.system().lower().startswith("win"):
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        self._log(
            f"[Vast.ai] Abriendo tunel local {self.local_host}:{self.local_port} "
            f"-> {self.remote_host}:{self.remote_port} ({self.ssh_host}:{self.ssh_port})"
        )
        self._tunnel_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        time.sleep(3)
        if self._tunnel_process.poll() is not None:
            raise RuntimeError("El tunel SSH de Vast.ai termino inmediatamente")

    def close_ssh_tunnel(self) -> None:
        proc = self._tunnel_process
        self._tunnel_process = None
        if not proc or proc.poll() is not None:
            return
        self._log("[Vast.ai] Cerrando tunel SSH")
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _register_atexit(self) -> None:
        if self._registered_atexit:
            return
        self._registered_atexit = True
        atexit.register(self.shutdown_on_exit)

    def attach_to_qt_app(self, app: Any) -> None:
        """Connect to QApplication.aboutToQuit — more reliable than atexit in PyQt apps.

        aboutToQuit fires while Qt is still alive but before Python tears down threads,
        so the requests.put has a real chance to send. atexit remains as a last-resort
        fallback (registered lazily inside ensure_ready).
        """
        if self._registered_qt:
            return
        if not self.enabled:
            self._log("[Vast.ai] attach_to_qt_app: manager deshabilitado, no se conecta")
            return
        try:
            app.aboutToQuit.connect(self.shutdown_on_exit)
            self._registered_qt = True
            self._log("[Vast.ai] Conectado a QApplication.aboutToQuit")
            # Also register atexit as fallback in case aboutToQuit is bypassed
            self._register_atexit()
        except Exception as exc:
            self._log(f"[Vast.ai] No se pudo conectar a aboutToQuit: {exc}")

    def shutdown_on_exit(self) -> None:
        """Stop the Vast.ai instance on app shutdown. Idempotent and bounded in time.

        Policy: always stop if `auto_stop_on_exit` is True and we have credentials,
        regardless of whether this session opened a tunnel. The user explicitly opted
        in via VAST_AUTO_STOP_ON_EXIT=1, and leaving the instance running burns money.
        """
        if self._shutdown_called:
            return
        self._shutdown_called = True

        self.close_ssh_tunnel()

        if not self.auto_stop_on_exit:
            self._log("[Vast.ai] shutdown_on_exit: auto_stop_on_exit=False, no se detiene")
            return
        if not (self.api_key and self.instance_id):
            self._log("[Vast.ai] shutdown_on_exit: falta api_key o instance_id")
            return

        # Direct request with short timeout — never block app shutdown for >10s.
        try:
            self._log(f"[Vast.ai] Deteniendo instancia {self.instance_id} (shutdown)")
            response = requests.put(
                f"{self.api_base_url}/instances/{self.instance_id}/",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"state": "stopped"},
                timeout=max(3, self.shutdown_timeout_seconds),
            )
            if response.ok:
                self._log(f"[Vast.ai] Stop request OK (HTTP {response.status_code})")
            else:
                body = (response.text or "")[:200]
                self._log(f"[Vast.ai] Stop request HTTP {response.status_code}: {body}")
        except Exception as exc:
            self._log(f"[Vast.ai] Stop request error: {exc}")

    def describe_safe(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "instance_id": self.instance_id,
            "api_key": _redact(self.api_key),
            "ssh_host": self.ssh_host,
            "ssh_port": self.ssh_port,
            "local": f"{self.local_host}:{self.local_port}",
            "remote": f"{self.remote_host}:{self.remote_port}",
            "auto_stop_on_exit": self.auto_stop_on_exit,
            "auto_failover": self.auto_failover,
        }


_DEFAULT_MANAGER: Optional[VastAiInstanceManager] = None


def get_default_vast_manager(log_callback=None) -> VastAiInstanceManager:
    global _DEFAULT_MANAGER
    if _DEFAULT_MANAGER is None:
        _DEFAULT_MANAGER = VastAiInstanceManager.from_env(log_callback=log_callback)
    elif log_callback and _DEFAULT_MANAGER.log_callback is None:
        _DEFAULT_MANAGER.log_callback = log_callback
    return _DEFAULT_MANAGER


__all__ = ["VastAiInstanceManager", "VastStartError", "get_default_vast_manager"]
