"""Evaluate provider-thinking.v1.json. No network calls or provider credentials."""
import json
import re
from pathlib import Path
from urllib.parse import urlparse

POLICY = json.loads(Path(__file__).with_name('provider-thinking.v1.json').read_text())


def normalize_thinking_mode(mode):
    # Preserve legacy values on load; validation rejects them before save/send.
    if mode is None:
        return 'default'
    if not isinstance(mode, str):
        raise ValueError('Thinking must be default, low, high or disabled')
    value = mode.strip().lower() or 'default'
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', value):
        raise ValueError('Thinking must be default, low, high or disabled')
    return value


def thinking_capabilities(base_url, model):
    host = (urlparse(base_url or '').hostname or '').lower()
    model = (model or '').strip().lower()
    for rule in POLICY['rules']:
        if any(host == h or (h.startswith('*.') and host.endswith(h[1:]) and host != h[2:]) for h in rule['hosts']) and re.fullmatch(rule['models'], model):
            return {'version': POLICY['version'], 'modes': ['default', *POLICY['profiles'][rule['profile']]], 'note': rule['note'], 'rule': rule}
    return {'version': POLICY['version'], 'modes': ['default'], 'note': 'Unverified endpoint/model: only default is available.', 'rule': None}


def thinking_parameters(base_url, model, mode):
    mode = normalize_thinking_mode(mode)
    capability = thinking_capabilities(base_url, model)
    if mode not in capability['modes']:
        raise ValueError(f"Unsupported Thinking '{mode}'. Supported: {', '.join(capability['modes'])}. {capability['note']}")
    if mode == 'default':
        return {}
    return json.loads(json.dumps(POLICY['profiles'][capability['rule']['profile']][mode]))
