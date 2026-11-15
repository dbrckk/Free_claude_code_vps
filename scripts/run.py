"""Run Free Claude Code and DeepSeek Harness behind a single authenticated edge."""

import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from diagnostics import Diagnostics

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("DATA_DIR", "/data"))
HOME = DATA / "home"
DSH_HOME = HOME / ".dsh"
WORKSPACE = DATA / "workspace"
PROFILE = DSH_HOME / "profiles" / "web" / "package.json"
TOKEN_FILE = DATA / "fcc-proxy-token"
FCC_CONFIG = HOME / ".fcc" / ".env"
FCC_PORT = 8082
DSH_PORT = 3080
TOKEN_PORT = 3082
RENDER = bool(os.environ.get("RENDER_EXTERNAL_URL"))
EDGE_PORT = int(os.environ.get("PORT", "10000"))
CUSTOM_ID = "custom_0c2a18eaf1ab49ab94254580ffecb0a2"
PROVIDERS = {
    "routeway": ("ROUTEWAY_API_KEY", "https://api.routeway.ai/v1", "deepseek-v4.1-flash:free", 42000),
    "unorouter": ("UNOROUTER_API_KEY", "https://api.unorouter.com/v1", "deepseek-v4.1-flash-1017:free", 1000000),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1", "deepseek/deepseek-v4.1-flash-1017:free", 1000000),
    "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com", "deepseek-flash", 1000000),
}
OPTIONAL_BUNDLES = (
    "plugin-market-bundle", "session-search", "terminal-bundle", "forge-bundle",
    "voice-input-bundle", "ralph-bundle", "auto-review", "badge-skill-bundle",
    "cot-translation-bundle",
)
HTTP = build_opener(ProxyHandler({}))
PROCESSES = []


def child_environment():
    excluded = {"WEB_PASSWORD", *(row[0] for row in PROVIDERS.values())}
    env = {key: value for key, value in os.environ.items() if key not in excluded}
    env.update(
        HOME=str(HOME),
        DSH_HOME=str(DSH_HOME),
        DSH_TELEMETRY_DISABLED="1",
        XDG_DATA_HOME=str(HOME / ".local" / "share"),
        XDG_CONFIG_HOME=str(HOME / ".config"),
        GIT_TERMINAL_PROMPT="0",
    )
    return env


def edge_settings():
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    origin = os.environ.get("PUBLIC_URL", "").rstrip("/") or render_url or "http://localhost:8080"
    parsed = urlsplit(origin)
    if (
        not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)(?::[0-9]{1,5})?", parsed.netloc)
        or parsed.scheme not in ("http", "https")
        or (parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1"))
        or parsed.path or parsed.query or parsed.fragment
        or parsed.port == 0
    ):
        raise ValueError("PUBLIC_URL doit être une origine HTTPS ou une URL HTTP locale.")
    user = os.environ.get("WEB_USERNAME", "admin")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", user):
        raise ValueError("WEB_USERNAME doit contenir 1 à 64 caractères alphanumériques ou ._-")
    password = os.environ.get("WEB_PASSWORD", "")
    if password and not (16 <= len(password.encode()) <= 72 and not set("\r\n") & set(password)):
        raise ValueError("WEB_PASSWORD doit contenir entre 16 et 72 octets sur une ligne.")
    return origin, parsed.netloc, parsed.scheme, user, password


def model_settings():
    selected = os.environ.get("MODEL_PROVIDER", "routeway")
    if selected not in PROVIDERS:
        raise ValueError("MODEL_PROVIDER doit être routeway, unorouter, openrouter ou deepseek.")
    key_name, base, model, context = PROVIDERS[selected]
    return selected, os.environ.get(key_name, "").strip(), base, model, context


def write_profile():
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    patch = PROFILE.parent / "cordis.patch.yml"
    if not patch.exists() or not patch.stat().st_size:
        patch.write_text("[]\n")
    if PROFILE.exists():
        return
    optional = ("plugin-market-bundle",) if RENDER else OPTIONAL_BUNDLES
    bundles = ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app",
               *(f"@deepseek-ai/dsh-experimental-{name}" for name in optional)]
    manifest = {"name": "dsh-profile-web", "private": True, "dependencies": {},
                "dsh": {"profile": {"bundles": bundles}}}
    temporary = PROFILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(PROFILE)


def fcc_environment(include_key=False):
    _, key, base, model, _ = model_settings()
    provider = {
        "provider_id": CUSTOM_ID, "display_name": "DeepSeek V4.1 Flash",
        "base_url": base, "api_format": "openai_chat",
        "reasoning_format": "openai_effort", "model_ids": [model],
    }
    if include_key and key:
        provider["api_keys"] = [key]
    return child_environment() | {
        "HOST": "127.0.0.1", "PORT": str(FCC_PORT), "FCC_OPEN_BROWSER": "false",
        "FCC_ENV_FILE": str(FCC_CONFIG),
        "PROXY_AUTH_ENABLED": "true",
        "FCC_CUSTOM_PROVIDERS": json.dumps([provider]),
        "MODEL": f"{CUSTOM_ID}/{model}", "MODEL_FALLBACKS": "[]",
        "LOG_RAW_API_PAYLOADS": "false", "LOG_RAW_SSE_EVENTS": "false",
        "OTEL_SDK_DISABLED": "true", "DISABLE_TELEMETRY": "1",
        "DISABLE_NONESSENTIAL_TRAFFIC": "1",
    }


def configure_fcc():
    config_dir = FCC_CONFIG.parent
    config_dir.mkdir(parents=True, exist_ok=True)
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_urlsafe(32))
    token = TOKEN_FILE.read_text().strip()
    existing = FCC_CONFIG.read_text().splitlines() if FCC_CONFIG.exists() else ["FCC_CONFIG_SCHEMA=2"]
    lines = [line for line in existing if not re.match(r"^\s*(?:export\s+)?ANTHROPIC_AUTH_TOKEN\s*=", line)]
    lines.append(f"ANTHROPIC_AUTH_TOKEN={token}")
    temporary = FCC_CONFIG.with_name(".deploy.env")
    temporary.write_text("\n".join(lines) + "\n")
    temporary.replace(FCC_CONFIG)


def model_patch():
    _, _, _, model, context = model_settings()
    filename = DATA / "model.patch.json"
    # Route Harness to the same FCC Responses endpoint used by fcc-dsh.
    filename.write_text(json.dumps([{
        "id": "agent-default-model",
        "config": {"provider": "free-claude-code", "model": f"{CUSTOM_ID}/{model}"},
    }, {"id": "llm-deepseek", "disabled": True},
       {"id": "llm-deepseek-account", "disabled": True},
       {"id": "tool-web", "disabled": True},
       {"id": "web-search-deepseek", "disabled": True}, {
        "id": "llm-pi-ai",
        "config": {"providers": {"free-claude-code": {
            "displayName": "Free Claude Code",
            "apiKeyEnv": "FCC_DSH_API_KEY",
            "api": "openai-responses",
            "baseURL": f"http://127.0.0.1:{FCC_PORT}/v1",
            "models": [{
                "id": f"{CUSTOM_ID}/{model}", "name": "DeepSeek V4.1 Flash",
                "contextWindow": context, "input": ["text"] if context == 42000 else ["text", "image"],
                "reasoningEfforts": {"off": "none", "low": "low", "medium": "medium",
                                     "high": "high", "max": "max"},
            }],
            "retryPolicy": {"mode": "normal", "maxRetries": 0},
            "streamIdleTimeoutMs": 180000,
        }}},
    }]))
    return filename


def start(command, env, **kwargs):
    child = subprocess.Popen(command, env=env, cwd=WORKSPACE, start_new_session=True, **kwargs)
    PROCESSES.append(child)
    return child


def health(port, path="/healthz"):
    try:
        with HTTP.open(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
            return response.status == 200
    except (URLError, TimeoutError):
        return False


def wait_for_fcc(child):
    deadline = time.monotonic() + 45
    while child.poll() is None and time.monotonic() < deadline:
        if health(FCC_PORT, "/health"):
            return
        time.sleep(0.2)
    raise RuntimeError("Le proxy Free Claude Code n’a pas démarré.")


class HarnessLogin(BaseHTTPRequestHandler):
    boot_token = None
    diagnostics = None

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/_diagnostics", "/_diagnostics/state", "/_diagnostics/app.js", "/_diagnostics/style.css"):
            ready = self.boot_token is not None if path.endswith("/state") else False
            self.diagnostics.get(self, path, ready)
            return
        if path not in ("/", "/_login"):
            self.send_error(404)
            return
        if self.boot_token is None:
            self.send_error(503, "DeepSeek Harness is starting")
            return
        host = self.headers["Host"]
        request = Request(
            f"http://127.0.0.1:{DSH_PORT}/?" + urlencode({"token": self.boot_token}),
            headers={"Host": host},
        )
        # Never follow the upstream 303 here: pass the session cookie to the browser.
        try:
            with LOGIN_HTTP.open(request, timeout=5) as response:
                self.send_response(response.status)
                for name in ("Set-Cookie", "Location", "Cache-Control", "Referrer-Policy"):
                    if value := response.headers.get(name):
                        self.send_header(name, value)
                self.end_headers()
        except (URLError, TimeoutError):
            self.send_error(503, "DeepSeek Harness is starting")

    def do_POST(self):
        path = urlsplit(self.path).path
        if path in ("/_diagnostics/workspace", "/_diagnostics/model"):
            self.diagnostics.post(self, path)
        else:
            self.send_error(404)

    def log_message(self, *_):
        pass


class LoginRedirect(HTTPRedirectHandler):
    def http_error_303(self, request, response, code, message, headers):
        return response


LOGIN_HTTP = build_opener(ProxyHandler({}), LoginRedirect())


def record_harness_token(stream):
    for line in stream:
        match = re.search(r"^dsh web: https?://[^\s?]+/\?token=([A-Za-z0-9_-]{43})\s*$", line)
        if match:
            HarnessLogin.boot_token = match.group(1)
        else:
            print(re.sub(r"([?&]token=)[A-Za-z0-9_-]+", r"\1[masqué]", line), end="", flush=True)


def start_harness(origin, authority):
    env = child_environment() | {"FCC_DSH_API_KEY": TOKEN_FILE.read_text().strip()}
    if RENDER:
        env["NODE_OPTIONS"] = "--max-old-space-size=180 --max-semi-space-size=2"
    command = ["dsh", "web", "--patch", str(model_patch())]
    if not RENDER:
        command.extend(["--patch", str(ROOT / "config" / "harness.patch.yml")])
    child = start(
        [*command, "--no-open", "--host", "127.0.0.1", "--port", str(DSH_PORT),
         "--public-url", origin, "--trusted-host", authority],
        env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
    )
    Thread(target=record_harness_token, args=(child.stdout,), daemon=True).start()
    return child


def run():
    origin, authority, protocol, user, password = edge_settings()
    selected, key, _, model, _ = model_settings()
    for path in (DATA, HOME, WORKSPACE):
        path.mkdir(parents=True, exist_ok=True)
    env = child_environment()

    password_hash = subprocess.run(
        ["caddy", "hash-password", "--algorithm", "bcrypt", "--bcrypt-cost", "10"],
        input=(password or secrets.token_urlsafe(32)) + "\n", env=env,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    status = f"Fournisseur : {selected}. " + ("Clé configurée." if key else "Clé API à configurer.")
    child = start(["caddy", "run", "--config", str(ROOT / "config" / "Caddyfile"), "--adapter", "caddyfile"], env | {
        "EDGE_PORT": str(EDGE_PORT), "EDGE_HOST": authority.split(":")[0],
        "EDGE_USER": user, "EDGE_PASSWORD_HASH": password_hash, "EDGE_STATUS": status,
        "EDGE_LOCKED": "no" if password else "yes",
        "DSH_PORT": str(DSH_PORT), "DSH_LOGIN_PORT": str(TOKEN_PORT),
        "GOGC": "70", "GOMEMLIMIT": "28MiB",
        "EDGE_COOKIE_DIRECTIVE": r'header_down Set-Cookie "^(.+)$" "${1}; Secure"' if protocol == "https" else "",
    })
    print(f"Interface {origin} · {status}" if password else "Interface verrouillée : renseigner WEB_PASSWORD.", flush=True)
    if password:
        write_profile()
        configure_fcc()
        HarnessLogin.diagnostics = Diagnostics(
            origin, selected, bool(key), f"{CUSTOM_ID}/{model}", WORKSPACE, TOKEN_FILE, FCC_PORT, HTTP,
        )
        login = ThreadingHTTPServer(("127.0.0.1", TOKEN_PORT), HarnessLogin)
        Thread(target=login.serve_forever, daemon=True).start()
        wait_for_fcc(start(["fcc-server"], fcc_environment(include_key=True)))
        start_harness(origin, authority)
    while all(process.poll() is None for process in PROCESSES):
        time.sleep(0.5)
    raise RuntimeError(f"Un des services s’est arrêté (proxy HTTP : {child.poll()}).")


def stop(signum, frame):
    raise SystemExit(0)


def terminate_children():
    for child in reversed(PROCESSES):
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 12
    for child in PROCESSES:
        try:
            child.wait(max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()


def main():
    os.umask(0o077)
    if sys.argv[1:2] == ["health"]:
        return 0 if health(EDGE_PORT) else 1
    if sys.argv[1:2] == ["claude"]:
        env = fcc_environment()
        os.chdir(WORKSPACE)
        os.execvpe("fcc-claude", ["fcc-claude", *sys.argv[2:]], env)
    if sys.argv[1:]:
        raise ValueError("Commande inconnue.")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        run()
    finally:
        terminate_children()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Démarrage impossible : {error}", file=sys.stderr)
        sys.exit(1)
