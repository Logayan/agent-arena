from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from .secret_store import SecretStorageError


class LLMConfigurationError(RuntimeError):
    pass


class LLMRequestError(RuntimeError):
    pass


RetryCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


async def _notify_retry(callback: RetryCallback | None, payload: dict[str, Any]) -> None:
    if callback is None:
        return
    result = callback(payload)
    if inspect.isawaitable(result):
        await result


class AnthropicCompatibleClient:
    """Real Anthropic Messages API client.

    No mock/fallback path is provided intentionally. Missing credentials,
    rate limits, provider errors and malformed model output are surfaced to
    the caller as failures.
    """

    def __init__(self, *, base_url: str | None = None, token: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url if base_url is not None else os.getenv("ANTHROPIC_BASE_URL", "")).rstrip("/")
        self.token = token if token is not None else os.getenv("ANTHROPIC_AUTH_TOKEN", "")
        self.model = model if model is not None else os.getenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "")
        if not self.base_url or not self.token or not self.model:
            raise LLMConfigurationError(
                "Missing ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN or ANTHROPIC_DEFAULT_SONNET_MODEL"
            )

    async def message(
        self,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 4096,
        on_retry: RetryCallback | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        response: httpx.Response | None = None
        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=90) as client:
                    response = await client.post(
                        f"{self.base_url}/v1/messages",
                        headers={
                            "x-api-key": self.token,
                            "Authorization": f"Bearer {self.token}",
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json=body,
                    )
            except httpx.HTTPError as exc:
                if attempt < 3:
                    delay = 2 ** (attempt - 1)
                    await _notify_retry(on_retry, {
                        "attempt": attempt,
                        "max_attempts": 3,
                        "next_attempt": attempt + 1,
                        "delay_seconds": delay,
                        "reason": "network_error",
                        "error_type": type(exc).__name__,
                        "error_detail": str(exc) or type(exc).__name__,
                        "model": self.model,
                    })
                    await asyncio.sleep(delay)
                    continue
                detail = str(exc) or type(exc).__name__
                raise LLMRequestError(f"LLM network failure after 3 attempts: {detail}") from exc
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                delay = 2 ** (attempt - 1)
                await _notify_retry(on_retry, {
                    "attempt": attempt,
                    "max_attempts": 3,
                    "next_attempt": attempt + 1,
                    "delay_seconds": delay,
                    "reason": "provider_http_error",
                    "http_status": response.status_code,
                    "error_type": "HTTPStatusError",
                    "error_detail": response.text[:1000],
                    "model": self.model,
                })
                await asyncio.sleep(delay)
                continue
            break
        if response is None:
            raise LLMRequestError("LLM request did not return a response")
        if response.status_code >= 400:
            detail = response.text[:2000]
            raise LLMRequestError(f"LLM provider returned HTTP {response.status_code}: {detail}")
        try:
            return response.json()
        except ValueError as exc:
            raise LLMRequestError("LLM provider returned invalid JSON") from exc

    async def json_message(
        self,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 4096,
        on_retry: RetryCallback | None = None,
    ) -> dict[str, Any]:
        response = await self.message(prompt, system=system, max_tokens=max_tokens, on_retry=on_retry)
        content = response.get("content")
        if not isinstance(content, list):
            raise LLMRequestError("LLM response has no content blocks")
        text = "".join(str(block.get("text", "")) for block in content if isinstance(block, dict))
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
        candidate = fenced.group(1) if fenced else text.strip()
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise LLMRequestError(f"LLM returned non-JSON workflow output: {text[:500]}") from exc
        if not isinstance(value, dict):
            raise LLMRequestError("LLM JSON output must be an object")
        return value


class OpenAIResponsesClient(AnthropicCompatibleClient):
    """OpenAI Responses API client, including gateways that require SSE."""

    async def message(
        self,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 4096,
        on_retry: RetryCallback | None = None,
    ) -> dict[str, Any]:
        content = []
        if system:
            content.append({"role": "system", "content": [{"type": "input_text", "text": system}]})
        content.append({"role": "user", "content": [{"type": "input_text", "text": prompt}]})
        body = {"model": self.model, "input": content, "max_output_tokens": max_tokens, "stream": True}
        max_text_chars = max(4000, max_tokens * 5)
        completed: dict[str, Any] | None = None
        text_parts: list[str] = []
        for attempt in range(1, 4):
            completed = None
            text_parts = []
            try:
                async with httpx.AsyncClient(timeout=90) as client:
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/v1/responses",
                        headers={"Authorization": f"Bearer {self.token}", "content-type": "application/json"},
                        json=body,
                    ) as response:
                        if response.status_code >= 400:
                            detail = (await response.aread()).decode(errors="replace")[:2000]
                            if response.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                                delay = 2 ** (attempt - 1)
                                await _notify_retry(on_retry, {
                                    "attempt": attempt,
                                    "max_attempts": 3,
                                    "next_attempt": attempt + 1,
                                    "delay_seconds": delay,
                                    "reason": "provider_http_error",
                                    "http_status": response.status_code,
                                    "error_type": "HTTPStatusError",
                                    "error_detail": detail,
                                    "model": self.model,
                                })
                                await asyncio.sleep(delay)
                                continue
                            raise LLMRequestError(f"LLM provider returned HTTP {response.status_code}: {detail}")
                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            payload = line[6:]
                            if payload == "[DONE]":
                                continue
                            try:
                                event = json.loads(payload)
                            except json.JSONDecodeError:
                                continue
                            if event.get("type") == "response.output_text.delta":
                                delta = str(event.get("delta", ""))
                                remaining = max_text_chars - sum(len(item) for item in text_parts)
                                if remaining > 0:
                                    text_parts.append(delta[:remaining])
                                if len(delta) > remaining:
                                    completed = {"model": self.model, "usage": {}, "platform_truncated": True}
                                    break
                            if event.get("type") == "response.completed" and isinstance(event.get("response"), dict):
                                completed = event["response"]
            except httpx.HTTPError as exc:
                if attempt < 3:
                    delay = 2 ** (attempt - 1)
                    await _notify_retry(on_retry, {
                        "attempt": attempt,
                        "max_attempts": 3,
                        "next_attempt": attempt + 1,
                        "delay_seconds": delay,
                        "reason": "network_error",
                        "error_type": type(exc).__name__,
                        "error_detail": str(exc) or type(exc).__name__,
                        "model": self.model,
                    })
                    await asyncio.sleep(delay)
                    continue
                detail = str(exc) or type(exc).__name__
                raise LLMRequestError(f"LLM network failure after 3 attempts: {detail}") from exc
            if completed is not None:
                break
            if attempt < 3:
                delay = 2 ** (attempt - 1)
                await _notify_retry(on_retry, {
                    "attempt": attempt,
                    "max_attempts": 3,
                    "next_attempt": attempt + 1,
                    "delay_seconds": delay,
                    "reason": "incomplete_stream",
                    "error_type": "IncompleteResponseStream",
                    "error_detail": "响应流未返回 response.completed 事件",
                    "model": self.model,
                })
                await asyncio.sleep(delay)
        if completed is None:
            raise LLMRequestError("LLM response stream ended without response.completed after 3 attempts")
        usage = completed.get("usage") if isinstance(completed.get("usage"), dict) else {}
        return {
            "id": completed.get("id"),
            "model": completed.get("model", self.model),
            "content": [{"type": "text", "text": "".join(text_parts)}],
            "usage": usage,
        }


def client_for_config(*, provider: str, base_url: str, token: str, model: str) -> AnthropicCompatibleClient:
    if provider == "openai-responses":
        return OpenAIResponsesClient(base_url=base_url, token=token, model=model)
    return AnthropicCompatibleClient(base_url=base_url, token=token, model=model)


def configured_llm() -> AnthropicCompatibleClient:
    from .platform_store import platform_store

    try:
        config = platform_store.get_active_model_config(include_secret=True)
    except SecretStorageError as exc:
        raise LLMConfigurationError(str(exc)) from exc
    if config:
        return client_for_config(
            provider=str(config["provider"]),
            base_url=str(config["base_url"]),
            token=str(config["token"]),
            model=str(config["model"]),
        )
    return AnthropicCompatibleClient()
