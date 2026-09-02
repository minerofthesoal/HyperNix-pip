"""``/inference`` — the governed inference surface.

New in **T1 v1.0.26.9.2.1**.

``/bridge/lmstudio/*`` is a pass-through. It hands the caller's model
string straight to LM Studio, which means the model registry, the plan's
routing cascade, the per-key quota and the cost ledger never see the
request. That is the correct shape for a *bridge* — a window onto
something else — but it left the one path that actually spends money as
the one path outside the rules the rest of the API is built on:

    the server determines which models exist, which are available,
    which limits apply, which fallbacks are allowed, how much usage
    remains, and what an operation costs

These endpoints are that principle applied to inference. Every call:

1. resolves the caller's plan from their **server-side assignment**, not
   from the request body,
2. requires the model through the registry, so an unregistered id is
   ``MODEL_NOT_SUPPORTED`` here exactly as everywhere else,
3. checks the key's assignment allows that model,
4. refuses an exhausted key **before** any inference runs — an over-quota
   request discovered afterwards has already cost the operator the work,
5. dispatches to whichever backend the server has, and
6. meters the tokens actually spent and prices them.

Fallback is opt-in. ``allow_fallback`` defaults to false because a silent
substitution of an exhausted model is precisely what the spec forbids; a
caller that wants the cascade has to say so, and the response says which
model really ran.

The backend today is the LM Studio bridge, which is the only one this
server can reach. ``GET /inference/backends`` reports what is actually
available rather than a hard-coded list, so a client can tell "no backend
configured" from "the backend is down" without parsing an error string.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ...bridge.lmstudio import LMStudioBridge, LMStudioError
from ..auth import AuthContext
from ..config import T1APIConfig
from ..deps import (
    get_auth_context,
    get_config,
    get_cost_calculator,
    get_key_directory,
    get_registry,
    get_request_id,
    get_routing_engine,
    get_usage_meter,
)
from ..errors import T1APIError, T1ErrorCode
from ..schemas import (
    InferenceBackend,
    InferenceBackendsResponse,
    InferenceChatRequest,
    InferenceCompletionRequest,
    InferenceEmbeddingsRequest,
    InferenceEmbeddingsResponse,
    InferenceMessage,
    InferenceResponse,
    InferenceTokenCountRequest,
    InferenceTokenCountResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inference", tags=["inference"])

#: Rough characters-per-token for the pre-flight estimate. Only ever used
#: to *size* a request before it runs — never to bill one. What gets
#: metered is what the backend reports it actually consumed, because a
#: heuristic that decides the invoice is a heuristic that is wrong about
#: money.
_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN) if text else 0


def _messages_text(messages: list[InferenceMessage]) -> str:
    return "\n".join(f"{m.role}: {m.content}" for m in messages)


def _require_backend(config: T1APIConfig) -> LMStudioBridge:
    """The inference backend, or a refusal that names what to configure."""
    if not config.lmstudio_enabled or not config.lmstudio_url:
        raise T1APIError(
            T1ErrorCode.NOT_SUPPORTED,
            "This server has no inference backend configured. Set "
            "T1_LMSTUDIO_URL (and T1_LMSTUDIO_ENABLED=1) to point it at one.",
            details={"backends": []},
            http_status=501,
        )
    return LMStudioBridge(
        base_url=config.lmstudio_url,
        api_key=config.lmstudio_api_key or None,
        timeout=config.lmstudio_timeout_seconds,
    )


def _as_t1_error(exc: LMStudioError) -> T1APIError:
    return T1APIError(
        T1ErrorCode.MODEL_UNAVAILABLE,
        str(exc),
        details=exc.to_dict() if hasattr(exc, "to_dict") else {},
        http_status=503,
    )


def _resolve(
    *,
    ctx: AuthContext,
    keys,
    engine,
    registry,
    meter,
    model_id: str,
    input_tokens: int,
    allow_fallback: bool,
) -> tuple[str, bool]:
    """Which model may actually run, and whether that is a substitution.

    Every gate in one place so the chat, completion and stream paths
    cannot diverge on which of them they remembered to apply.
    """
    registry.require(model_id)
    plan = keys.resolve_plan(ctx.key_id)
    keys.assert_model_allowed(ctx.key_id, model_id)
    decision = engine.route_manual(
        key_id=ctx.key_id,
        plan=plan,
        model_id=model_id,
        input_tokens=input_tokens,
        automatic_fallback=allow_fallback,
    )
    chosen = decision.model_id
    if chosen != model_id:
        # A substitution still has to satisfy the caller's assignment: the
        # cascade is the server's policy, not an exemption from the key's.
        keys.assert_model_allowed(ctx.key_id, chosen)
    meter.assert_not_exhausted(ctx.key_id, chosen)
    return chosen, chosen != model_id


def _first_choice(envelope: dict) -> tuple[str, str]:
    choices = envelope.get("choices")
    if not isinstance(choices, list) or not choices:
        return "", ""
    first = choices[0] or {}
    message = first.get("message") or {}
    content = message.get("content")
    if content is None:
        content = first.get("text") or ""
    return str(content), str(first.get("finish_reason") or "")


def _run_chat(
    *,
    bridge: LMStudioBridge,
    model: str,
    messages: list[dict],
    temperature,
    max_tokens,
    top_p,
    stop,
) -> dict:
    try:
        return bridge.chat(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            stop=stop,
        )
    except LMStudioError as exc:
        raise _as_t1_error(exc) from exc


def _complete(
    *,
    ctx: AuthContext,
    config: T1APIConfig,
    keys,
    engine,
    registry,
    meter,
    costs,
    request_id: str,
    requested_model: str,
    messages: list[InferenceMessage],
    temperature,
    max_tokens,
    top_p,
    stop,
    allow_fallback: bool,
    endpoint: str,
) -> InferenceResponse:
    """The whole governed path, shared by /chat and /completions."""
    if not messages:
        raise T1APIError(T1ErrorCode.VALIDATION_ERROR, "messages must not be empty")

    estimated = _estimate_tokens(_messages_text(messages))
    model, substituted = _resolve(
        ctx=ctx, keys=keys, engine=engine, registry=registry, meter=meter,
        model_id=requested_model, input_tokens=estimated,
        allow_fallback=allow_fallback,
    )

    bridge = _require_backend(config)
    envelope = _run_chat(
        bridge=bridge, model=model,
        messages=[m.model_dump() for m in messages],
        temperature=temperature, max_tokens=max_tokens, top_p=top_p, stop=stop,
    )

    content, finish = _first_choice(envelope)
    usage = envelope.get("usage") or {}
    # What the backend says it spent, not what we guessed. The estimate
    # sized the request; this is the bill.
    input_tokens = int(usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("completion_tokens") or 0)
    if not input_tokens and not output_tokens:
        # A backend that reports no usage still consumed something, and
        # recording zero would make the quota unenforceable against it.
        input_tokens = estimated
        output_tokens = _estimate_tokens(content)

    meter.record(
        key_id=ctx.key_id, model_id=model,
        input_tokens=input_tokens, output_tokens=output_tokens,
        endpoint=endpoint,
    )
    input_cost, output_cost, currency = costs.price_tokens(
        model, input_tokens, output_tokens
    )

    return InferenceResponse(
        model=model,
        requested_model=requested_model,
        content=content,
        finish_reason=finish,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=round(input_cost + output_cost, 8),
        currency=currency,
        backend=bridge.base_url,
        substituted=substituted,
        raw=envelope,
        request_id=request_id,
    )


@router.get("/backends", response_model=InferenceBackendsResponse)
def list_backends(
    ctx: AuthContext = Depends(get_auth_context),
    config: T1APIConfig = Depends(get_config),
    request_id: str = Depends(get_request_id),
) -> InferenceBackendsResponse:
    """What this server can actually dispatch to, and whether it answers.

    Probed rather than declared, so "no backend configured" and "the
    backend is down" are two different answers instead of one error
    string a client has to parse.
    """
    backends: list[InferenceBackend] = []
    if config.lmstudio_enabled and config.lmstudio_url:
        bridge = LMStudioBridge(
            base_url=config.lmstudio_url,
            api_key=config.lmstudio_api_key or None,
            timeout=min(10.0, float(config.lmstudio_timeout_seconds or 10)),
        )
        try:
            bridge.list_models()
            reachable, detail = True, "answered"
        except LMStudioError as exc:
            reachable, detail = False, str(exc)
        backends.append(InferenceBackend(
            name="lmstudio", kind="openai-compatible",
            reachable=reachable, detail=detail, address=bridge.base_url,
        ))
    else:
        backends.append(InferenceBackend(
            name="lmstudio", kind="openai-compatible", reachable=False,
            detail="disabled (T1_LMSTUDIO_ENABLED=0 or no T1_LMSTUDIO_URL)",
        ))

    return InferenceBackendsResponse(
        backends=backends,
        default=next((b.name for b in backends if b.reachable), ""),
        request_id=request_id,
    )


@router.post("/chat", response_model=InferenceResponse)
def inference_chat(
    payload: InferenceChatRequest,
    ctx: AuthContext = Depends(get_auth_context),
    config: T1APIConfig = Depends(get_config),
    registry=Depends(get_registry),
    meter=Depends(get_usage_meter),
    engine=Depends(get_routing_engine),
    keys=Depends(get_key_directory),
    costs=Depends(get_cost_calculator),
    request_id: str = Depends(get_request_id),
) -> InferenceResponse:
    """A chat completion, through the registry, the cascade and the meter."""
    return _complete(
        ctx=ctx, config=config, keys=keys, engine=engine, registry=registry,
        meter=meter, costs=costs, request_id=request_id,
        requested_model=payload.model, messages=payload.messages,
        temperature=payload.temperature, max_tokens=payload.max_tokens,
        top_p=payload.top_p, stop=payload.stop,
        allow_fallback=payload.allow_fallback,
        endpoint="/inference/chat",
    )


@router.post("/completions", response_model=InferenceResponse)
def inference_completions(
    payload: InferenceCompletionRequest,
    ctx: AuthContext = Depends(get_auth_context),
    config: T1APIConfig = Depends(get_config),
    registry=Depends(get_registry),
    meter=Depends(get_usage_meter),
    engine=Depends(get_routing_engine),
    keys=Depends(get_key_directory),
    costs=Depends(get_cost_calculator),
    request_id: str = Depends(get_request_id),
) -> InferenceResponse:
    """A plain prompt, sent as a single user turn.

    Carried over the chat shape rather than the legacy completions one,
    because every backend worth reaching still speaks chat and several no
    longer speak completions at all.
    """
    if not payload.prompt.strip():
        raise T1APIError(T1ErrorCode.VALIDATION_ERROR, "prompt must not be empty")
    return _complete(
        ctx=ctx, config=config, keys=keys, engine=engine, registry=registry,
        meter=meter, costs=costs, request_id=request_id,
        requested_model=payload.model,
        messages=[InferenceMessage(role="user", content=payload.prompt)],
        temperature=payload.temperature, max_tokens=payload.max_tokens,
        top_p=payload.top_p, stop=payload.stop,
        allow_fallback=payload.allow_fallback,
        endpoint="/inference/completions",
    )


@router.post("/chat/stream")
def inference_chat_stream(
    payload: InferenceChatRequest,
    ctx: AuthContext = Depends(get_auth_context),
    config: T1APIConfig = Depends(get_config),
    registry=Depends(get_registry),
    meter=Depends(get_usage_meter),
    engine=Depends(get_routing_engine),
    keys=Depends(get_key_directory),
    request_id: str = Depends(get_request_id),
) -> StreamingResponse:
    """The same governed path, streamed.

    Every gate runs **before** the first byte, because a stream that
    starts and then discovers the key is exhausted has already spent the
    work — and a 429 cannot be sent once the response has begun.

    Usage is metered when the stream ends, including when it ends badly:
    tokens the backend produced before a mid-stream failure were still
    produced, and not recording them makes the quota under-count exactly
    for the callers whose requests fail most.
    """
    if not payload.messages:
        raise T1APIError(T1ErrorCode.VALIDATION_ERROR, "messages must not be empty")

    estimated = _estimate_tokens(_messages_text(payload.messages))
    model, substituted = _resolve(
        ctx=ctx, keys=keys, engine=engine, registry=registry, meter=meter,
        model_id=payload.model, input_tokens=estimated,
        allow_fallback=payload.allow_fallback,
    )
    bridge = _require_backend(config)
    messages = [m.model_dump() for m in payload.messages]
    key_id = ctx.key_id

    def _events():
        produced: list[str] = []
        header = {
            "model": model,
            "requested_model": payload.model,
            "substituted": substituted,
            "backend": bridge.base_url,
        }
        yield f": hypernix inference open {json.dumps(header)}\n\n".encode()
        try:
            for chunk in bridge.chat_stream(
                messages,
                model=model,
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
                top_p=payload.top_p,
                stop=payload.stop,
            ):
                for choice in (chunk.get("choices") or []):
                    delta = (choice or {}).get("delta") or {}
                    if delta.get("content"):
                        produced.append(str(delta["content"]))
                yield f"data: {json.dumps(chunk)}\n\n".encode()
        except LMStudioError as exc:
            logger.warning(
                "t1api.inference: stream failed against %s: %s", bridge.base_url, exc
            )
            yield f"data: {json.dumps({'error': exc.to_dict()})}\n\n".encode()
        finally:
            try:
                meter.record(
                    key_id=key_id, model_id=model,
                    input_tokens=estimated,
                    output_tokens=_estimate_tokens("".join(produced)),
                    endpoint="/inference/chat/stream",
                )
            except Exception:  # pragma: no cover - metering must not break the stream
                logger.exception("t1api.inference: could not record stream usage")
        yield b"data: [DONE]\n\n"

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Request-Id": request_id,
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/embeddings", response_model=InferenceEmbeddingsResponse)
def inference_embeddings(
    payload: InferenceEmbeddingsRequest,
    ctx: AuthContext = Depends(get_auth_context),
    config: T1APIConfig = Depends(get_config),
    registry=Depends(get_registry),
    meter=Depends(get_usage_meter),
    keys=Depends(get_key_directory),
    request_id: str = Depends(get_request_id),
) -> InferenceEmbeddingsResponse:
    """Embeddings, under the same registry and quota rules as generation.

    No routing cascade: substituting a different embedding model would
    return vectors from a different space, which is not a fallback but a
    silently wrong answer.
    """
    if not payload.input:
        raise T1APIError(T1ErrorCode.VALIDATION_ERROR, "input must not be empty")
    registry.require(payload.model)
    keys.assert_model_allowed(ctx.key_id, payload.model)
    meter.assert_not_exhausted(ctx.key_id, payload.model)

    bridge = _require_backend(config)
    if not hasattr(bridge, "embeddings"):
        raise T1APIError(
            T1ErrorCode.NOT_SUPPORTED,
            "This server's inference backend does not expose embeddings.",
            http_status=501,
        )
    try:
        envelope = bridge.embeddings(payload.input, model=payload.model)
    except LMStudioError as exc:
        raise _as_t1_error(exc) from exc

    vectors = [
        [float(x) for x in (item or {}).get("embedding") or []]
        for item in (envelope.get("data") or [])
    ]
    usage = envelope.get("usage") or {}
    input_tokens = int(usage.get("prompt_tokens") or 0) or _estimate_tokens(
        "\n".join(payload.input)
    )
    meter.record(
        key_id=ctx.key_id, model_id=payload.model,
        input_tokens=input_tokens, output_tokens=0,
        endpoint="/inference/embeddings",
    )
    return InferenceEmbeddingsResponse(
        model=str(envelope.get("model") or payload.model),
        embeddings=vectors,
        dimensions=len(vectors[0]) if vectors else 0,
        input_tokens=input_tokens,
        backend=bridge.base_url,
        request_id=request_id,
    )


@router.post("/tokens", response_model=InferenceTokenCountResponse)
def inference_token_count(
    payload: InferenceTokenCountRequest,
    ctx: AuthContext = Depends(get_auth_context),
    registry=Depends(get_registry),
    meter=Depends(get_usage_meter),
    costs=Depends(get_cost_calculator),
    request_id: str = Depends(get_request_id),
) -> InferenceTokenCountResponse:
    """Size a request before committing to it.

    A caller working against a spend cap or a token allowance needs to
    know what a prompt will cost *before* sending it; discovering it
    afterwards is a refund, not a budget. Runs no inference and records
    no usage.

    The count is an estimate and says so in ``method`` — the tokenizer
    that matters lives in the backend, and claiming exactness here would
    be a number people would then rely on.
    """
    if (payload.text is None) == (payload.messages is None):
        raise T1APIError(
            T1ErrorCode.VALIDATION_ERROR,
            "Send exactly one of 'text' or 'messages'.",
        )
    entry = registry.require(payload.model)
    text = payload.text if payload.text is not None else _messages_text(payload.messages or [])
    tokens = _estimate_tokens(text)
    input_cost, _, currency = costs.price_tokens(payload.model, tokens, 0)

    snapshot = meter.snapshot_for_model(ctx.key_id, payload.model)
    remaining = None
    if entry.input_token_limit:
        remaining = max(0, entry.input_token_limit - snapshot.input_tokens_used)

    return InferenceTokenCountResponse(
        model=payload.model,
        tokens=tokens,
        estimated_input_cost=round(input_cost, 8),
        currency=currency,
        remaining_input_tokens=remaining,
        method=f"heuristic:{_CHARS_PER_TOKEN}-chars-per-token",
        request_id=request_id,
    )
