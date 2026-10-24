"""FastAPI route handlers."""

import json
from collections.abc import AsyncIterable, Mapping

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import ValidationError
from starlette.responses import StreamingResponse

from free_claude_code.application.errors import ApplicationError
from free_claude_code.application.ports import ProviderResolver, RequestRuntimeLease
from free_claude_code.config.model_refs import parse_provider_type
from free_claude_code.config.settings import Settings
from free_claude_code.core.anthropic import (
    MessagesRequest,
    TokenCountRequest,
    get_token_count,
)
from free_claude_code.core.anthropic.task_policy import allow_background_subagents
from free_claude_code.core.openai_responses import (
    OpenAIResponsesRequest,
    openai_error_payload,
)
from free_claude_code.core.trace import trace_event
from free_claude_code.core.version import package_version

from .dependencies import (
    get_services,
    get_settings,
    require_anthropic_proxy_auth,
    require_proxy_auth,
    resolve_provider,
)
from .handlers import MessagesHandler, ResponsesHandler, TokenCountHandler
from .model_catalog import (
    ModelCatalogView,
    ModelsListResponse,
    build_models_list_response,
    build_muse_models_list_response,
)
from .openai_chat import (
    completion_id,
    error_to_openai,
    to_chunks,
    to_completion,
    to_messages_request,
)
from .ports import ApiServices
from .request_errors import ordinary_application_error_response
from .request_ids import get_request_id
from .response_streams import bind_response_lifetime

router = APIRouter()


def _provider_resolver(lease: RequestRuntimeLease) -> ProviderResolver:
    return lambda provider_type: resolve_provider(provider_type, lease=lease)


async def _create_messages_response(
    services: ApiServices,
    request_data: MessagesRequest,
    *,
    request_id: str,
    request_headers: Mapping[str, str] | None = None,
) -> object:
    lease: RequestRuntimeLease | None = None
    try:
        lease = await services.requests.acquire()
        await lease.wait_for_token_estimation()
        allow_background_subagents(lease.settings.allow_background_subagents)
        handler = MessagesHandler(
            lease.settings,
            web_tools=services.web_tools,
            provider_resolver=_provider_resolver(lease),
            token_counter=get_token_count,
            generation_id=lease.generation_id,
            request_headers=request_headers,
            model_info_lookup=lease.model_info,
        )
        response = await handler.create(request_data, request_id=request_id)
    except ApplicationError as exc:
        if lease is not None:
            await lease.release()
        return ordinary_application_error_response(
            exc,
            wire_api="messages",
            request_id=request_id,
        )
    except BaseException:
        if lease is not None:
            await lease.release()
        raise
    assert lease is not None
    return await bind_response_lifetime(response, lease.release)


async def _create_responses_response(
    services: ApiServices,
    request_data: OpenAIResponsesRequest,
    *,
    request_id: str,
    request_headers: Mapping[str, str] | None = None,
) -> object:
    lease: RequestRuntimeLease | None = None
    try:
        lease = await services.requests.acquire()
        await lease.wait_for_token_estimation()
        handler = ResponsesHandler(
            lease.settings,
            provider_resolver=_provider_resolver(lease),
            generation_id=lease.generation_id,
            request_headers=request_headers,
        )
        response = await handler.create(request_data, request_id=request_id)
    except ApplicationError as exc:
        if lease is not None:
            await lease.release()
        return ordinary_application_error_response(
            exc,
            wire_api="responses",
            request_id=request_id,
        )
    except BaseException:
        if lease is not None:
            await lease.release()
        raise
    assert lease is not None
    return await bind_response_lifetime(response, lease.release)


def _probe_response(allow: str) -> Response:
    return Response(status_code=204, headers={"Allow": allow})


@router.post("/v1/messages")
async def create_message(
    request: Request,
    request_data: MessagesRequest,
    services: ApiServices = Depends(get_services),
    _auth=Depends(require_anthropic_proxy_auth),
):
    """Create a message (JSON by default; stream=true returns Anthropic SSE)."""
    return await _create_messages_response(
        services,
        request_data,
        request_id=get_request_id(request),
        request_headers=request.headers,
    )


@router.api_route("/v1/messages", methods=["HEAD", "OPTIONS"])
async def probe_messages(_auth=Depends(require_anthropic_proxy_auth)):
    return _probe_response("POST, HEAD, OPTIONS")


@router.post("/v1/responses")
async def create_response(
    request: Request,
    request_data: OpenAIResponsesRequest,
    services: ApiServices = Depends(get_services),
    _auth=Depends(require_proxy_auth),
):
    """Create an OpenAI Responses-compatible response through this proxy."""
    return await _create_responses_response(
        services,
        request_data,
        request_id=get_request_id(request),
        request_headers=request.headers,
    )


@router.api_route("/v1/responses", methods=["HEAD", "OPTIONS"])
async def probe_responses(_auth=Depends(require_proxy_auth)):
    return _probe_response("POST, HEAD, OPTIONS")


@router.post("/v1/chat/completions")
async def create_chat_completion(
    request: Request,
    services: ApiServices = Depends(get_services),
    _auth=Depends(require_proxy_auth),
):
    """OpenAI Chat Completions (JSON, or chunks with stream=true) for the many
    tools that speak it, through the same pipeline as /v1/messages."""
    request_id = get_request_id(request)
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(
            status_code=400,
            content=openai_error_payload(
                message="The request body must be a JSON object.",
                error_type="invalid_request_error",
            ),
        )
    try:
        messages = to_messages_request(body)
    except ApplicationError as exc:
        return ordinary_application_error_response(
            exc, wire_api="responses", request_id=request_id
        )
    except ValidationError as exc:
        return JSONResponse(
            status_code=400,
            content=openai_error_payload(
                message=f"Invalid request: {exc.errors()[0].get('msg', exc)}",
                error_type="invalid_request_error",
            ),
        )
    options = body.get("stream_options")
    response = await _create_messages_response(
        services,
        messages,
        request_id=request_id,
        request_headers=request.headers,
    )
    return _as_chat(
        response,
        model=messages.model,
        include_usage=isinstance(options, dict) and bool(options.get("include_usage")),
    )


class _ChatChunks:
    """The translated stream; closing it also closes the stream it reads, even
    when the client left before the first chunk."""

    def __init__(
        self, source: AsyncIterable[object], *, model: str, include_usage: bool
    ) -> None:
        self._source = source
        self._chunks = to_chunks(
            source,
            model=model,
            cid=completion_id(),
            include_usage=include_usage,
        )

    def __aiter__(self) -> _ChatChunks:
        return self

    async def __anext__(self) -> bytes:
        return await self._chunks.__anext__()

    async def aclose(self) -> None:
        try:
            await self._chunks.aclose()
        finally:
            close = getattr(self._source, "aclose", None)
            if close is not None:
                await close()


def _as_chat(response: object, *, model: str, include_usage: bool) -> object:
    if isinstance(response, StreamingResponse):
        response.body_iterator = _ChatChunks(
            response.body_iterator, model=model, include_usage=include_usage
        )
        return response
    if isinstance(response, JSONResponse):
        content = json.loads(bytes(response.body) or b"{}")
        if response.status_code >= 400:
            return JSONResponse(
                status_code=response.status_code,
                content=error_to_openai(content, response.status_code),
            )
        return JSONResponse(
            content=to_completion(content, model=model, cid=completion_id())
        )
    return response


@router.api_route("/v1/chat/completions", methods=["HEAD", "OPTIONS"])
async def probe_chat_completions(_auth=Depends(require_proxy_auth)):
    return _probe_response("POST, HEAD, OPTIONS")


@router.post("/v1/messages/count_tokens")
async def count_tokens(
    request: Request,
    request_data: TokenCountRequest,
    services: ApiServices = Depends(get_services),
    _auth=Depends(require_anthropic_proxy_auth),
):
    """Count tokens for a request."""
    lease = await services.requests.acquire()
    try:
        await lease.wait_for_token_estimation()
        handler = TokenCountHandler(lease.settings, token_counter=get_token_count)
        return handler.count(request_data, request_id=get_request_id(request))
    finally:
        await lease.release()


@router.api_route("/v1/messages/count_tokens", methods=["HEAD", "OPTIONS"])
async def probe_count_tokens(_auth=Depends(require_anthropic_proxy_auth)):
    return _probe_response("POST, HEAD, OPTIONS")


@router.get("/")
async def root(
    settings: Settings = Depends(get_settings),
    _auth=Depends(require_proxy_auth),
):
    return {
        "status": "ok",
        "provider": parse_provider_type(settings.model),
        "model": settings.model,
    }


@router.api_route("/", methods=["HEAD", "OPTIONS"])
async def probe_root():
    return _probe_response("GET, HEAD, OPTIONS")


# The version this server started with: the desktop app compares it with the
# files on disk and restarts a server left running from an older version.
_STARTED_VERSION = package_version()


@router.get("/health")
async def health():
    return {"status": "healthy", "version": _STARTED_VERSION}


@router.api_route("/health", methods=["HEAD", "OPTIONS"])
async def probe_health():
    return _probe_response("GET, HEAD, OPTIONS")


@router.get(
    "/v1/models",
    response_model=ModelsListResponse,
    response_model_exclude_none=True,
)
async def list_models(
    view: ModelCatalogView | None = None,
    x_fcc_model_view: ModelCatalogView | None = Header(default=None),
    services: ApiServices = Depends(get_services),
    _auth=Depends(require_proxy_auth),
):
    """List the model ids this proxy advertises to compatible clients."""
    trace_event(stage="ingress", event="free_claude_code.api.models.list", source="api")
    snapshot = await services.requests.wait_for_catalog()
    return build_models_list_response(
        snapshot.settings,
        snapshot,
        view=view or x_fcc_model_view or ModelCatalogView.CLAUDE,
    )


@router.get(
    "/muse-code/models",
    response_model=ModelsListResponse,
    response_model_exclude_none=True,
)
async def list_muse_models(
    services: ApiServices = Depends(get_services),
    _auth=Depends(require_proxy_auth),
):
    """List the direct Responses models expected by Muse Code."""
    trace_event(stage="ingress", event="free_claude_code.api.models.list", source="api")
    snapshot = await services.requests.wait_for_catalog()
    return build_muse_models_list_response(snapshot.settings, snapshot)


@router.post("/stop")
async def stop_cli(
    services: ApiServices = Depends(get_services),
    _auth=Depends(require_proxy_auth),
):
    """Stop all CLI sessions and pending tasks."""
    result = await services.tasks.stop_all()
    if result is None:
        raise HTTPException(status_code=503, detail="Messaging system not initialized")
    if result.source is not None:
        logger.info("STOP_CLI: source={} cancelled_count=N/A", result.source)
        return {"status": "stopped", "source": result.source}

    count = result.cancelled_count or 0
    trace_event(
        stage="ingress",
        event="free_claude_code.api.cli.stop_via_messaging_workflow",
        source="api",
        cancelled_nodes=count,
    )
    logger.info("STOP_CLI: source=messaging_workflow cancelled_count={}", count)
    return {"status": "stopped", "cancelled_count": count}
