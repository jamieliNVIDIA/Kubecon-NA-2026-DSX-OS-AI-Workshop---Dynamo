#!/usr/bin/env python3
"""Run inside a candidate runtime: package/model/CLI inspection, no GPU or download."""
import importlib.metadata as metadata
import json
import os
from pathlib import Path


def inspect():
    versions = {}
    errors = []
    for name in ('ai-dynamo', 'ai-dynamo-runtime', 'vllm', 'torch', 'transformers', 'nixl'):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
            if name != 'nixl':
                errors.append('Missing package: ' + name)
    expected = os.environ.get('EXPECTED_DYNAMO_VERSION')
    if expected and any(versions[k] != expected for k in ('ai-dynamo', 'ai-dynamo-runtime')):
        errors.append('Dynamo packages do not both match expected version ' + expected)
    architecture = 'NemotronH_Omni_Reasoning_V3'
    supported = None
    fields = []
    try:
        from vllm.model_executor.models import ModelRegistry
        supported = architecture in ModelRegistry.get_supported_archs()
        if not supported:
            errors.append('vLLM registry does not advertise ' + architecture)
        from vllm.engine.arg_utils import EngineArgs
        fields = sorted(EngineArgs.__dataclass_fields__)
        for name in ('language_model_only', 'enforce_eager', 'max_num_seqs', 'tensor_parallel_size'):
            if name not in fields:
                errors.append('Missing engine argument: ' + name)
        from dynamo.common.model_fetch import fetch_model
        if not callable(fetch_model):
            errors.append('Dynamo metadata resolver is not callable')
    except Exception as exc:
        errors.append(type(exc).__name__ + ': ' + str(exc))
    devices = [str(p) for p in Path('/dev').glob('nvidia[0-9]*')]
    if devices:
        errors.append('CPU probe unexpectedly has numbered GPU devices')
    return {'status': 'passed' if not errors else 'failed', 'versions': versions,
            'architecture': architecture, 'architecture_registered': supported,
            'engine_fields': fields, 'numbered_gpu_devices': devices, 'errors': errors,
            'scope': 'Unmodified container CPU imports/model registry/argument fields only; no weights, GPU kernels, serving or feature-composition qualification.'}


if __name__ == '__main__':
    result = inspect()
    print(json.dumps(result), flush=True)
    raise SystemExit(0 if result['status'] == 'passed' else 1)
