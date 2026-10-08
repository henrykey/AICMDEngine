"""Keep explicit image COPY manifests complete for runtime modules."""
from pathlib import Path
import shlex

import pytest


PACKAGE = Path(__file__).resolve().parents[1] / "mcp/servers/PDF2MDEnhanced"


@pytest.mark.parametrize("dockerfile", ["Dockerfile", "Dockerfile.cn"])
def test_image_copies_all_runtime_python_modules(dockerfile):
    copied = set()
    for line in (PACKAGE / dockerfile).read_text().splitlines():
        if not line.startswith("COPY "):
            continue
        tokens = shlex.split(line)
        if tokens and tokens[0] == "COPY" and tokens[-1] == "/app/PDF2MDEnhanced/":
            copied.update(tokens[1:-1])
    required = {path.name for path in PACKAGE.glob("*.py")} | {"provider-thinking.v1.json"}
    assert not required - copied, f"{dockerfile} omits runtime modules: {sorted(required - copied)}"
