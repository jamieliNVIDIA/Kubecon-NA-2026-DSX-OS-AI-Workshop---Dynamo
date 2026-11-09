"""Format projected shell commands without changing the argv that executes."""
from __future__ import annotations

import json
import shlex
import textwrap


def shell_command(arguments, *, width=100):
    """Wrap only between shell words; quoted JSON, paths and URLs stay intact."""
    lines, current = [], ''
    for argument in arguments:
        word = shlex.quote(str(argument))
        candidate = current + (' ' if current else '') + word
        if current and len(candidate) > width - 2:
            lines.append(current + ' \\')
            current = '  ' + word
        else:
            current = candidate
    if current:
        lines.append(current)
    return '\n'.join(lines)


def prose(value, *, width=100):
    """Wrap explanatory text, leaving code and executable values to their renderers."""
    return '\n\n'.join(textwrap.fill(paragraph, width=width, break_long_words=False,
                                    break_on_hyphens=False)
                       for paragraph in value.split('\n\n'))


def request_text(body, *, filename='request.json'):
    """Project request settings and readable prompts; keep the full JSON on disk."""
    lines = ['Request body: (full JSON: ' + str(filename) + ')']
    lines.extend(f'  {key}: {json.dumps(value, ensure_ascii=False)}'
                 for key, value in body.items() if key != 'messages')
    for index, message in enumerate(body.get('messages', []), 1):
        lines.append(f'  Message {index} · {message.get("role", "unknown")}:')
        content = message.get('content', '')
        if isinstance(content, str):
            text = '\n'.join(textwrap.fill(line, width=96,
                                           subsequent_indent=line[:len(line) - len(line.lstrip())],
                                           replace_whitespace=False, break_long_words=False,
                                           break_on_hyphens=False) for line in content.splitlines())
        else:
            text = json.dumps(content, ensure_ascii=False)
        lines.extend('    ' + line for line in text.splitlines())
    return '\n'.join(lines)


def response_text(response):
    """Show the generated answer as text instead of escaped JSON or stream chunks."""
    content = response.get('content')
    choices = response.get('choices') or []
    if content is None and len(choices) == 1:
        content = choices[0].get('message', {}).get('content')
    if not isinstance(content, str):
        return json.dumps(response, indent=2, ensure_ascii=False)
    lines = ['Assistant response:', content]
    for key, label in (('prefill_worker_id', 'Prefill worker'), ('decode_worker_id', 'Decode worker')):
        worker = response.get('worker') or {}
        if worker.get(key) is not None:
            lines.append(label + ': ' + str(worker[key]))
    tokens = (response.get('usage') or {}).get('completion_tokens')
    if tokens is not None:
        lines.append('Output tokens: ' + str(tokens))
    return '\n'.join(lines)
