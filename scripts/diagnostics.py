"""Diagnostics for the owner, served behind the authenticated edge."""

import json
import os
import re
import tempfile
import time
from http import HTTPStatus
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import Request

from free_router import KEY_NAME, MODEL, SETUP_URL

ASSETS = Path(__file__).resolve().parent.parent / "config"
PROBE_COOLDOWN = 60


class Diagnostics:
    def __init__(self, origin, key_configured, model_ref, workspace, token_file, fcc_port, http):
        self.origin = origin
        self.key_configured = key_configured
        self.model_ref = model_ref
        self.workspace = workspace
        self.token_file = token_file
        self.fcc_url = f"http://127.0.0.1:{fcc_port}/v1"
        self.http = http
        self.probe_lock = Lock()
        self.last_probe = float("-inf")

    def fcc_request(self, path, payload=None):
        request = Request(
            self.fcc_url + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={
                "Authorization": "Bearer " + self.token_file.read_text().strip(),
                "Content-Type": "application/json",
            },
        )
        with self.http.open(request, timeout=3 if payload is None else 20) as response:
            if payload is None:
                return json.load(response)
            for _ in range(256):
                line = response.readline(64 * 1024)
                if not line:
                    break
                if line.startswith(b"data: ") and line.strip() != b"data: [DONE]":
                    event = json.loads(line[6:])
                    if event.get("type") == "response.completed":
                        return event["response"]
                    if event.get("type") in ("response.failed", "response.incomplete", "error"):
                        return event.get("response") or event
            return {}

    def proxy_ready(self):
        try:
            return self.fcc_request("/models?view=responses").get("default_model_id") == self.model_ref
        except (OSError, ValueError, AttributeError):
            return False

    def status(self, harness_ready):
        service_id = os.environ.get("RENDER_SERVICE_ID", "")
        render_url = (
            f"https://dashboard.render.com/web/{service_id}/env"
            if re.fullmatch(r"srv-[a-z0-9]+", service_id) else None
        )
        return {
            "provider": "OpenRouter",
            "model": MODEL,
            "keyConfigured": self.key_configured,
            "keyName": KEY_NAME,
            "providerSetupUrl": SETUP_URL,
            "renderEnvironmentUrl": render_url,
            "harnessReady": harness_ready,
            "proxyReady": self.proxy_ready(),
        }

    def check_workspace(self):
        try:
            with tempfile.TemporaryDirectory(prefix=".fcc-check-", dir=self.workspace) as temp:
                sample = Path(temp) / "verification.txt"
                sample.write_text("OK", encoding="utf-8")
                if sample.read_text(encoding="utf-8") == "OK":
                    return HTTPStatus.OK, "L’écriture, la lecture et le nettoyage ont réussi."
        except OSError:
            pass
        return HTTPStatus.SERVICE_UNAVAILABLE, "Le serveur n’a pas pu vérifier l’espace de travail."

    def check_model(self):
        if not self.key_configured:
            return HTTPStatus.CONFLICT, "Ajoute OPENROUTER_API_KEY dans les variables du serveur."
        if not self.proxy_ready():
            return HTTPStatus.SERVICE_UNAVAILABLE, "Free Claude Code termine son démarrage. Réessaie dans un instant."

        with self.probe_lock:
            now = time.monotonic()
            if now - self.last_probe < PROBE_COOLDOWN:
                return HTTPStatus.TOO_MANY_REQUESTS, "Attends une minute entre deux vérifications du modèle."
            self.last_probe = now

        try:
            response = self.fcc_request("/responses", {
                "model": self.model_ref,
                "input": "Reply with exactly OK.",
                "reasoning": {"effort": "none"},
                "max_output_tokens": 32,
                "stream": True,
                "store": False,
            })
            message = "".join(
                part.get("text", "")
                for item in response.get("output", [])
                if item.get("type") == "message"
                for part in item.get("content", [])
                if part.get("type") == "output_text"
            ).strip()
            if response.get("status") == "completed" and message:
                return HTTPStatus.OK, "OpenRouter a répondu via Free Claude Code."
            error = response.get("error") or {}
            code = error.get("code") or response.get("code")
            if code in ("rate_limit_exceeded", "insufficient_quota"):
                return HTTPStatus.BAD_GATEWAY, "OpenRouter signale une limite de quota ou une restriction du compte."
            if code in ("authentication_error", "invalid_api_key", "permission_denied"):
                return HTTPStatus.BAD_GATEWAY, "La clé ou l’accès au modèle a été refusé."
            if code == "model_not_found":
                return HTTPStatus.BAD_GATEWAY, "Aucun modèle compatible n’est disponible chez OpenRouter."
        except HTTPError as error:
            with error:
                if error.code in (401, 403):
                    return HTTPStatus.BAD_GATEWAY, "La clé ou l’accès au modèle a été refusé."
                if error.code in (402, 429):
                    return HTTPStatus.BAD_GATEWAY, "OpenRouter signale une limite de quota ou une restriction du compte."
                if error.code == 404:
                    return HTTPStatus.BAD_GATEWAY, "Aucun modèle compatible n’est disponible chez OpenRouter."
        except (TimeoutError, URLError):
            return HTTPStatus.GATEWAY_TIMEOUT, "Le modèle n’a pas répondu à temps."
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return HTTPStatus.BAD_GATEWAY, "Aucune réponse exploitable n’est revenue du fournisseur."

    def get(self, handler, path, harness_ready):
        if path == "/_diagnostics/state":
            self.send_json(handler, HTTPStatus.OK, self.status(harness_ready))
        else:
            file, content_type = {
                "/_diagnostics": ("diagnostics.html", "text/html"),
                "/_diagnostics/app.js": ("diagnostics.js", "text/javascript"),
                "/_diagnostics/style.css": ("diagnostics.css", "text/css"),
            }[path]
            self.send(handler, HTTPStatus.OK, content_type, (ASSETS / file).read_bytes())

    def post(self, handler, path):
        if (
            handler.headers.get("Origin") != self.origin
            or handler.headers.get("Content-Length", "0") != "0"
            or handler.headers.get("Transfer-Encoding")
        ):
            self.send_json(handler, HTTPStatus.FORBIDDEN, {"message": "Requête refusée."})
            return

        probe = self.check_workspace if path == "/_diagnostics/workspace" else self.check_model
        status, message = probe()
        self.send_json(handler, status, {"message": message})

    @staticmethod
    def send_json(handler, status, data):
        Diagnostics.send(handler, status, "application/json", json.dumps(data).encode())

    @staticmethod
    def send(handler, status, content_type, body):
        handler.send_response(status)
        handler.send_header("Content-Type", content_type + "; charset=utf-8")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        )
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
