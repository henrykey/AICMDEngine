import pytest
from src.llm.thinking import thinking_parameters

@pytest.mark.parametrize('host,model,mode,expected', [
 ('api.openai.com','gpt-5.1','disabled',{'reasoning_effort':'none'}),
 ('api.deepseek.com','deepseek-flash','low',{'thinking':{'type':'enabled'},'reasoning_effort':'low'}),
 ('dashscope.aliyuncs.com','qwen3.8-27b','high',{'enable_thinking':True,'reasoning_effort':'xhigh'}),
 ('api.z.ai','glm-5.3','low',{'reasoning_effort':'low'}),
 ('api.moonshot.ai','kimi-k3','high',{'reasoning_effort':'high'}),
])
def test_verified_mapping(host,model,mode,expected):
    assert thinking_parameters('https://'+host+'/v1',model,mode)==expected

@pytest.mark.parametrize('host,model,mode', [
 ('api.z.ai','glm-5.2','low'),('api.moonshot.ai','kimi-k3','disabled'),
 ('api.openai.com','unknown','low'),('api.openai.com.evil.test','gpt-5.1','low'),
 ('dashscope.aliyuncs.com','qwen3-vl-plus','high'),('api.openai.com','gpt-5.1','enabled')])
def test_unsupported_never_silently_maps(host,model,mode):
    with pytest.raises(ValueError): thinking_parameters('https://'+host+'/v1',model,mode)


def test_shared_cases_and_packaged_copies():
    import importlib.util
    from pathlib import Path
    from src.llm.thinking import POLICY
    root = Path(__file__).resolve().parents[1]
    package = root / 'mcp/servers/PDF2MDEnhanced'
    spec = importlib.util.spec_from_file_location('packaged_thinking', package / 'thinking_policy.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (root/'src/llm/thinking.py').read_bytes() == (package/'thinking_policy.py').read_bytes()
    for copy in [package/'provider-thinking.v1.json', root/'plan2/src/services/provider-thinking.v1.json']:
        assert copy.read_bytes() == (root/'src/llm/provider-thinking.v1.json').read_bytes()
    for case in POLICY['cases']:
        for resolve in [thinking_parameters, module.thinking_parameters]:
            if case.get('error'):
                with pytest.raises(ValueError): resolve(case['base_url'],case['model'],case['mode'])
            else:
                assert resolve(case['base_url'],case['model'],case['mode']) == case['expected']
