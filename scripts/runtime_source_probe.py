"""Read selected installed package integration source; no runtime mutation."""
import importlib.util
import json
from pathlib import Path
r={}
for package in ('modelexpress','dynamo'):
    spec=importlib.util.find_spec(package)
    roots=list(spec.submodule_search_locations or []) if spec else []
    for root in roots:
        for p in Path(root).rglob('*.py'):
            if package=='modelexpress' or 'envs' in p.name:
                text=p.read_text()
                r[str(p)]=text[:100000]
print(json.dumps(r))
