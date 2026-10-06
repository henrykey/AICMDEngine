"""Offline provider thinking persistence and wire-parameter contracts."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from src.llm.config_loader import LLMConfig
from src.llm.provider_manager import LLMProviderManager
from src.llm.thinking import normalize_thinking_mode, thinking_parameters
from src.routers.llm import create_provider, update_provider, test_provider as run_test

@pytest.mark.parametrize('mode,expected', [('default', {}), ('', {}), ('enabled', {'reasoning_effort': 'medium'}), ('disabled', {'reasoning_effort': 'none'}), (' LOW ', {'reasoning_effort': 'low'})])
def test_ollama_and_openai(mode, expected):
    for host in ['http://localhost:11434/v1', 'http://relay:2086/v1', 'https://api.openai.com/v1']:
        assert thinking_parameters(host, 'qwen3:8b', mode) == expected

@pytest.mark.parametrize('host', ['api.deepseek.com','api.z.ai','open.bigmodel.cn','api.moonshot.cn','api.moonshot.ai','api.kimi.com','api.kimi.ai'])
def test_cloud_thinking(host):
    assert thinking_parameters('https://'+host, 'test-model', 'disabled') == {'thinking': {'type':'disabled'}}
    assert thinking_parameters('https://'+host, 'test-model', 'low') == {'thinking': {'type':'enabled'}, 'reasoning_effort':'low'}

def test_qwen_and_forced_models():
    assert thinking_parameters('https://dashscope.aliyuncs.com/v1','kimi-k3','low') == {'enable_thinking':True,'reasoning_effort':'low'}
    for host, model in [('api.moonshot.ai','kimi-k3'),('api.z.ai','glm-5.3')]:
        with pytest.raises(ValueError): thinking_parameters('https://'+host,model,'disabled')
        with pytest.raises(ValueError): thinking_parameters('https://'+host,model,'medium')
        assert thinking_parameters('https://'+host,model,'enabled') == {}
        assert thinking_parameters('https://'+host,model,'low') == {'reasoning_effort':'low'}

def test_config_roundtrip_and_validation():
    for mode in ['default','enabled','disabled','low','max']:
        config=LLMConfig.from_dict({'name':'fixture','thinking_mode':mode})
        assert LLMConfig.from_dict(config.to_dict()).thinking_mode == mode
    assert LLMConfig.from_dict({'name':'old'}).thinking_mode == 'default'
    for bad in ['bad value', 'x'*33, {}, 1]:
        with pytest.raises(ValueError): normalize_thinking_mode(bad)

@pytest.mark.parametrize('create', [True,False])
def test_save_normalizes_and_invalid_mode_never_writes(create):
    async def check():
        manager=MagicMock()
        manager.get_providers.return_value={'fixture':object()}
        collection=manager.db_client.__getitem__.return_value.llm_providers
        collection.update_one=AsyncMock(return_value=SimpleNamespace(matched_count=1))
        manager.config_loader.load_from_mongodb=AsyncMock(return_value={})
        manager.initialize=AsyncMock()
        async def save(payload):
            return await create_provider(payload,manager) if create else await update_provider('fixture',payload,manager)
        await save({'name':'fixture','thinking_mode':' LOW '})
        assert collection.update_one.call_args.args[1]['$set']['thinking_mode']=='low'
        collection.update_one.reset_mock()
        with pytest.raises(HTTPException) as error: await save({'name':'fixture','thinking_mode':'bad value'})
        assert error.value.status_code==400
        collection.update_one.assert_not_called()
    asyncio.run(check())

def test_test_and_actual_calls_share_mapping_without_cross_provider_leak():
    async def check():
        manager=LLMProviderManager(MagicMock())
        client=MagicMock()
        client.chat.completions.create=AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='answer'))],usage=None))
        for name, mode in [('one','low'),('two','default')]:
            manager.providers[name]=LLMConfig.from_dict({'name':name,'base_url':'http://localhost:11434/v1','model':'gemma4:31b','thinking_mode':mode})
            manager.clients[name]=client
        assert (await run_test('one',{'message':'hi'},manager))['success']
        assert client.chat.completions.create.call_args.kwargs['extra_body']=={'reasoning_effort':'low'}
        await manager.complete([],provider='two')
        assert 'extra_body' not in client.chat.completions.create.call_args.kwargs
        await manager.complete([],provider='one',extra_body={'seed':1})
        assert client.chat.completions.create.call_args.kwargs['extra_body']=={'seed':1,'reasoning_effort':'low'}
        await manager.complete([],provider='one',reasoning_effort='high')
        assert 'extra_body' not in client.chat.completions.create.call_args.kwargs
    asyncio.run(check())
