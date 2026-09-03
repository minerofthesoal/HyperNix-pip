"""hypernix.quant.hyprslug_server — serve an extension GGUF over HTTP.

    hypernix hyprslug-headers serve model.iq09.gguf --port 1234

The mechanism that keeps the tier. :func:`hypernix.quant.hyprslug_headers.wrap`
makes a sub-bit model open in LM Studio by turning it into something
else; this makes it *reachable* from LM Studio while it is still a
0.9-bit model, by putting :mod:`hypernix.models.hnxrun` behind the
endpoint everything already speaks.

Why the standard library
------------------------
The rest of this package's HTTP lives in :mod:`hypernix.t1api`, which is
FastAPI and an optional extra. Requiring it here would mean a user whose
0.9-bit model will not open in LM Studio has to install a web framework
before finding out why — on the machine that is short of memory, which
is why they quantised to 0.9 bits. So this is ``http.server``: no extra,
no build, and one fewer thing between the model and the answer.

What it implements
------------------
``GET /v1/models``, ``POST /v1/chat/completions`` and
``POST /v1/completions``, non-streaming, plus ``GET /health``. That is
the subset LM Studio, Bionic, and every OpenAI client use to hold a
conversation. Streaming is not implemented: hnxrun generates a token at
a time already, but a chunked SSE response that stalls mid-stream is a
worse failure than a slow complete one, and at these bitrates the whole
reply arrives in about the time a stream's first token would.

Bound to loopback by default. ``--host 0.0.0.0`` is available and is a
decision to publish an unauthenticated inference endpoint on the
network, which the command says out loud rather than leaving to be
noticed.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["ServerError", "HyprslugModel", "build_server", "serve"]

#: Refuse a body larger than this rather than reading it into memory. A
#: prompt is kilobytes; anything at this size is a mistake or an attack,
#: and both are better answered with 413 than with an allocation.
MAX_BODY_BYTES = 8 << 20


class ServerError(RuntimeError):
    """The server could not start."""


class HyprslugModel:
    """One loaded model, and the two things a request can ask of it.

    Holds the :class:`~hypernix.models.hnxrun.LoadedModel` open for the
    life of the process. A sub-bit load is the expensive one — it is the
    tier whose whole point is that the *file* is small — so reloading per
    request would spend the saving on latency instead of memory.
    """

    def __init__(self, path: str | Path, *, cache_bytes: int = 0,
                 name: str = "", device: str = "auto") -> None:
        from ..models import hnxrun
        from .hyprslug_headers import HeaderError, resolve_model_path

        # A directory is accepted: LM Studio's layout puts the file in
        # <publisher>/<name>/<name>.gguf, which is what install-model
        # writes and what tab-completion stops at.
        try:
            self.path = resolve_model_path(path)
        except HeaderError as exc:
            raise ServerError(str(exc)) from exc
        try:
            self.model = hnxrun.load_model(
                self.path, cache_bytes=cache_bytes, device=device
            )
        except hnxrun.HnxEnvironmentError as exc:
            # Not the model's fault, so not reported against its name.
            raise ServerError(str(exc)) from exc
        except hnxrun.HnxRunError as exc:
            raise ServerError(f"{self.path}: {exc}") from exc
        self.name = name or self.path.stem
        self.loaded_at = time.time()

    @property
    def has_tokenizer(self) -> bool:
        return self.model.tokenizer is not None

    def describe(self) -> dict[str, Any]:
        from .hyprslug_headers import read_header

        header = read_header(self.path)
        return {
            "id": self.name,
            "object": "model",
            "created": int(self.loaded_at),
            "owned_by": "hypernix",
            # Beyond the OpenAI shape, because "why is this slow" and
            # "what am I actually talking to" are the two questions a
            # client has and neither has a field in the spec.
            "hypernix": {
                "path": str(self.path),
                "tier": header.tier or "upstream",
                "family": header.family,
                "bits_per_weight_on_disk": header.bits_per_weight,
                "resident_bits_per_weight": round(
                    self.model.resident_bits_per_weight, 4
                ),
                "resident_bytes": self.model.resident_bytes,
                "architecture": self.model.config.architecture,
                "context_length": self.model.config.context_length,
                "tokenizer": bool(self.has_tokenizer),
                "runtime": "hypernix.models.hnxrun",
                "device": str(self.model.device),
                "device_bytes": self.model.device_bytes,
            },
        }

    def complete(self, prompt: str, *, max_tokens: int = 256,
                 temperature: float = 0.7, seed: int | None = None) -> str:
        from ..models import hnxrun

        if not self.has_tokenizer:
            raise ServerError(
                f"{self.path} carries no tokenizer metadata, so text cannot be "
                f"turned into tokens for it. Convert the model with a tool that "
                f"writes tokenizer.ggml.*."
            )
        return hnxrun.continue_text(
            self.model, prompt,
            max_new_tokens=max_tokens, temperature=temperature, seed=seed,
        )


def _model_errors() -> tuple[type[BaseException], ...]:
    """The runtime's own refusals, which are 400s rather than 500s."""
    from ..models.hnxrun import HnxRunError

    return (HnxRunError,)


def _flatten(messages: list[dict[str, Any]]) -> str:
    """Chat messages as one plain prompt.

    The same flattening :mod:`hypernix.models.ggufrun` uses, and for the
    same reason: a model quantised to half a bit is not going to follow a
    chat template faithfully, and formatting its input as though it would
    dresses the output up as more structured than it is.
    """
    parts = []
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, list):
            # The OpenAI content-parts shape. Text only -- there is no
            # vision here, and silently dropping an image part is better
            # than refusing a request whose text is answerable.
            content = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        content = str(content).strip()
        if content:
            parts.append(content)
    return "\n".join(parts)


def build_server(model: HyprslugModel, *, host: str = "127.0.0.1",
                 port: int = 1234) -> ThreadingHTTPServer:
    """An HTTP server exposing *model*. Call ``serve_forever`` on it."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "hyprslug-headers"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            logger.info("%s - %s", self.address_string(), fmt % args)

        # -- plumbing ---------------------------------------------------

        def _send(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            # A browser-based client (LM Studio's web UI, a WKWebView)
            # is subject to CORS where a Python client is not, and "it
            # works from curl but not from the app" is otherwise a very
            # long afternoon.
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.end_headers()
            self.wfile.write(body)

        def _fail(self, code: int, message: str, kind: str = "invalid_request_error"):
            self._send(code, {"error": {"message": message, "type": kind}})

        def _body(self) -> dict[str, Any] | None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                self._fail(413, f"Request body over {MAX_BODY_BYTES} bytes.")
                return None
            try:
                return json.loads(self.rfile.read(length) or b"{}")
            except ValueError as exc:
                self._fail(400, f"Body is not JSON: {exc}")
                return None

        # -- routes -----------------------------------------------------

        def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler
            self._send(200, {})

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") in ("/health", "/healthz"):
                self._send(200, {
                    "status": "ok",
                    "model": model.name,
                    "runtime": "hypernix.models.hnxrun",
                })
                return
            if self.path.rstrip("/") in ("/v1/models", "/api/v0/models"):
                self._send(200, {"object": "list", "data": [model.describe()]})
                return
            self._fail(404, f"No such route: {self.path}")

        def do_POST(self) -> None:  # noqa: N802
            route = self.path.rstrip("/")
            if route not in ("/v1/chat/completions", "/v1/completions"):
                self._fail(404, f"No such route: {self.path}")
                return
            payload = self._body()
            if payload is None:
                return

            chat = route.endswith("chat/completions")
            if chat:
                messages = payload.get("messages") or []
                if not isinstance(messages, list) or not messages:
                    self._fail(400, "chat/completions needs a non-empty messages list.")
                    return
                prompt = _flatten(messages)
            else:
                prompt = payload.get("prompt") or ""
                if isinstance(prompt, list):
                    prompt = "\n".join(str(p) for p in prompt)
            if not str(prompt).strip():
                self._fail(400, "The prompt is empty.")
                return

            if payload.get("stream"):
                self._fail(
                    400,
                    "This server does not stream. Send the same request with "
                    "stream=false; at these bitrates the whole reply arrives "
                    "in about the time a stream's first token would.",
                )
                return

            try:
                text = model.complete(
                    str(prompt),
                    max_tokens=int(payload.get("max_tokens") or 256),
                    temperature=float(payload.get("temperature", 0.7)),
                    seed=payload.get("seed"),
                )
            except ServerError as exc:
                self._fail(400, str(exc), kind="model_error")
                return
            except _model_errors() as exc:
                # A prompt this model cannot tokenise, an id outside the
                # vocabulary, a negative max_tokens: the request is
                # answerable and wrong, not the server broken. Returning
                # 500 for these sends a client looking at the wrong end.
                self._fail(400, str(exc), kind="model_error")
                return
            except Exception as exc:  # noqa: BLE001
                # A generation failure must not take the server with it:
                # this is the process holding the only loaded copy of a
                # model that took minutes to read.
                logger.exception("hyprslug-headers: generation failed")
                self._fail(500, f"Generation failed: {exc}", kind="model_error")
                return

            created = int(time.time())
            ident = f"chatcmpl-{uuid.uuid4().hex[:24]}"
            if chat:
                choice = {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            else:
                choice = {"index": 0, "text": text, "finish_reason": "stop"}
            self._send(200, {
                "id": ident,
                "object": "chat.completion" if chat else "text_completion",
                "created": created,
                "model": model.name,
                "choices": [choice],
                # Token counts are omitted rather than invented: this
                # runtime knows the generated count but not a
                # prompt-token count that would match anyone's tokenizer,
                # and a wrong number in this field silently corrupts
                # whatever is billing or budgeting on it.
                "usage": {},
            })

    try:
        return ThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        raise ServerError(
            f"Could not bind {host}:{port}: {exc}. Something else is probably "
            f"listening there — LM Studio's own server uses 1234."
        ) from exc


def serve(path: str | Path, *, host: str = "127.0.0.1", port: int = 1234,
          cache_bytes: int = 0, name: str = "", device: str = "auto",
          on_ready=None) -> None:
    """Load *path* and serve it until interrupted.

    ``on_ready`` is called once -- after the model is loaded *and* the
    port is bound, so a caller can announce the endpoint at the moment it
    starts answering. Announcing before this point is a promise the
    process may never keep: a sub-bit load takes a while and can fail, and
    the bind can be refused by whatever is already on 1234.
    """
    model = HyprslugModel(
        path, cache_bytes=cache_bytes, name=name, device=device
    )
    server = build_server(model, host=host, port=port)
    if on_ready is not None:
        on_ready(model)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
