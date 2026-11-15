"""Send Free Claude Code inference to OpenRouter's free-only route."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from secrets import compare_digest
from threading import Thread
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

PORT = 3083
MODEL = "openrouter/free"
KEY_NAME = "OPENROUTER_API_KEY"
SETUP_URL = "https://openrouter.ai/keys"
CHAT_PATH = "/v1/chat/completions"
UPSTREAM_URL = "https://openrouter.ai/api" + CHAT_PATH
MAX_BODY = 16 * 1024 * 1024

# Forward standard chat parameters only. OpenRouter extensions such as models,
# provider routing, and billable plugins must never come from the caller.
CHAT_FIELDS = frozenset({
    "model", "messages", "stream", "stream_options", "tools", "tool_choice",
    "parallel_tool_calls", "reasoning", "reasoning_effort", "max_tokens",
    "max_completion_tokens", "temperature", "top_p", "stop", "seed",
    "frequency_penalty", "presence_penalty", "response_format",
    "logit_bias", "logprobs", "top_logprobs",
})


def is_text_message(message):
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if content is None or isinstance(content, str):
        return True
    return isinstance(content, list) and all(
        isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)
        for part in content
    )


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


HTTP = build_opener(ProxyHandler({}), NoRedirect())


def start_free_router(key, token):
    class FreeRouter(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(185)
            super().setup()

        def do_POST(self):
            if self.path != CHAT_PATH:
                self.error(404, "Unknown endpoint.", "not_found")
                return
            authorization = self.headers.get("Authorization", "").encode("utf-8")
            if not compare_digest(authorization, b"Bearer " + token.encode()):
                self.error(401, "Invalid local proxy credentials.", "authentication_error")
                return
            if not key:
                self.error(503, "OPENROUTER_API_KEY is missing.", "service_unavailable")
                return
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    raise ValueError
                body = json.loads(self.rfile.read(length))
            except (ValueError, OSError, RecursionError):
                self.error(400, "Invalid chat request.", "invalid_request_error")
                return
            if not isinstance(body, dict) or body.get("model") != MODEL:
                self.error(400, "Only openrouter/free is enabled.", "invalid_request_error")
                return
            if body.keys() - CHAT_FIELDS:
                self.error(400, "Unsupported chat parameters.", "invalid_request_error")
                return
            messages = body.get("messages")
            if not isinstance(messages, list) or not messages or not all(map(is_text_message, messages)):
                self.error(400, "Only text messages are enabled.", "invalid_request_error")
                return
            definitions = body.get("tools", [])
            if not isinstance(definitions, list) or any(
                not isinstance(tool, dict) or tool.get("type") != "function"
                for tool in definitions
            ):
                self.error(400, "Only function tools are enabled.", "invalid_request_error")
                return
            self.forward(body)

        def forward(self, body):
            upstream_body = body | {
                "provider": {"max_price": {"prompt": 0, "completion": 0, "request": 0, "image": 0}},
                # Disable the legacy metered web plugin even if enabled on the account.
                "plugins": [{"id": "web", "enabled": False}],
            }
            request = Request(UPSTREAM_URL, data=json.dumps(upstream_body).encode(), headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            })
            try:
                upstream = HTTP.open(request, timeout=180)
            except HTTPError as error:
                with error:
                    status, code = {
                        400: (400, "invalid_request_error"),
                        401: (401, "authentication_error"),
                        402: (402, "insufficient_quota"),
                        403: (403, "permission_denied"),
                        404: (404, "model_not_found"),
                        429: (429, "rate_limit_exceeded"),
                        503: (503, "service_unavailable"),
                    }.get(error.code, (502, "upstream_error"))
                    self.error(status, f"OpenRouter returned HTTP {error.code}.", code)
                return
            except (OSError, ValueError):
                self.error(502, "OpenRouter could not be reached.", "upstream_error")
                return
            with upstream:
                try:
                    self.send_response(upstream.status)
                    self.send_header("Content-Type", upstream.headers.get_content_type())
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    while chunk := upstream.read1(65536):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except OSError:
                    # Either peer may disconnect during streaming.
                    return

        def error(self, status, message, code):
            body = json.dumps({"error": {"message": message, "type": code, "code": code}}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", PORT), FreeRouter)
    Thread(target=server.serve_forever, daemon=True).start()
    return server
