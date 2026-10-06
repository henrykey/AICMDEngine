"""Offline checks: provider secrets never enter diagnostics."""
import logging
import asyncio
from functools import wraps
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from src.llm.provider_manager import LLMProviderManager, safe_provider_error
from src.routers.llm import create_provider, update_provider, test_provider as run_provider_test

SECRET = "sk-offline-secret-fixture"


def run_async(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return run


@run_async
@pytest.mark.parametrize("create", [True, False])
async def test_update_logs_exclude_configuration_values(caplog, create):
    manager = MagicMock()
    manager.get_providers.return_value = {"fixture": object()}
    collection = manager.db_client.__getitem__.return_value.llm_providers
    collection.update_one = AsyncMock(return_value=SimpleNamespace(matched_count=1))
    manager.config_loader.load_from_mongodb = AsyncMock(return_value={})
    manager.initialize = AsyncMock()
    payload = {"name": "fixture", "api_key_ref": SECRET,
               "metadata": {"nested_secret": SECRET}, "capabilities_mode": "manual"}
    with caplog.at_level(logging.INFO):
        if create:
            await create_provider(payload, manager)
        else:
            await update_provider("fixture", payload, manager)
    assert SECRET not in caplog.text
    assert "set_count=" in caplog.text
    assert collection.update_one.call_args.args[1]["$set"]["api_key_ref"] == SECRET

@run_async
async def test_provider_failure_is_safe_in_logs_and_http(caplog):
    manager = LLMProviderManager(MagicMock())
    manager.providers["fixture"] = SimpleNamespace(base_url="https://example.invalid/v1", model="kimi-k3",
        temperature=1, max_tokens=100, top_p=1, timeout=30)
    failure = RuntimeError(SECRET)
    failure.status_code = 400
    failure.body = {"error": {"message": SECRET, "param": "top_p"}}
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=failure)
    manager.clients["fixture"] = client
    with caplog.at_level(logging.INFO), pytest.raises(HTTPException) as result:
        await run_provider_test("fixture", {"message": SECRET}, manager)
    assert result.value.status_code == 502
    assert result.value.detail == "Provider request failed; HTTP 400; parameter=top_p"
    assert SECRET not in caplog.text
    assert SECRET not in result.value.detail
    assert "raise_on_error" not in client.chat.completions.create.call_args.kwargs
    assert await manager.complete(messages=[], provider="fixture") is None


def test_untrusted_error_fields_cannot_be_returned():
    failure = RuntimeError(SECRET)
    failure.status_code = SECRET
    failure.body = {"error": {"param": SECRET, "message": SECRET}}
    assert safe_provider_error(failure) == "Provider request failed"


def test_dashscope_parameter_message_is_reconstructed_without_payload():
    failure = RuntimeError(SECRET)
    failure.status_code = 400
    failure.body = {"error": {"param": None, "message":
        "<400> InternalError.Algo.InvalidParameter: Parameter 'top_p'=1.0 is not supported for kimi-k3 model. " + SECRET}}
    assert safe_provider_error(failure) == (
        "Provider request failed; HTTP 400; parameter=top_p; configured value is not supported by this model")
    failure.body["error"]["message"] = "Parameter 'api_key_ref'=" + SECRET + " is not supported"
    assert safe_provider_error(failure) == "Provider request failed; HTTP 400"
