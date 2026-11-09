# Source from bash on the workshop jump host. No loopback API tunnel is used.
if [ -z "${BASH_VERSION:-}" ]; then
    printf 'Source kubecon-jump-env.sh from bash on the jump host.\n' >&2
    return 1
fi
_workshop_jump_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
_workshop_jump_python="$_workshop_jump_root/.venv/bin/python"
if [ ! -x "$_workshop_jump_python" ]; then
    # Existing qualification runners still accept the legacy environment path.
    _workshop_jump_python="$_workshop_jump_root/.local/venv/bin/python"
fi
if [ ! -x "$_workshop_jump_root/.local/bin/kubectl" ] || \
   [ ! -f "$_workshop_jump_root/.local/kubeconfig" ] || \
   [ ! -x "$_workshop_jump_python" ]; then
    printf 'Run uv sync --locked first; the jump-host workspace also needs .local/bin/kubectl and .local/kubeconfig.\n' >&2
    unset _workshop_jump_root _workshop_jump_python
    return 1
fi
_workshop_jump_env="${_workshop_jump_python%/bin/python}"
if [ -f "$_workshop_jump_env/bin/activate" ]; then
    source "$_workshop_jump_env/bin/activate"
fi
export VIRTUAL_ENV="$_workshop_jump_env"
export KUBECONFIG="$_workshop_jump_root/.local/kubeconfig"
export WORKSHOP_PYTHON="$_workshop_jump_python"
export PATH="$_workshop_jump_env/bin:$_workshop_jump_root/.local/bin:$HOME/.local/bin:$PATH"
# This contains only the source secret's namespace/name, never its credentials.
if [ -z "${WORKSHOP_PULL_SECRET_SOURCE:-}" ] && [ -f "$_workshop_jump_root/.local/pull-secret-source" ]; then
    export WORKSHOP_PULL_SECRET_SOURCE="$(cat "$_workshop_jump_root/.local/pull-secret-source")"
fi
if [ -z "${WORKSHOP_PULL_SECRET_SOURCE:-}" ]; then
    printf 'Set WORKSHOP_PULL_SECRET_SOURCE=namespace/name to an existing nvcr.io pull secret.\n' >&2
    unset _workshop_jump_root _workshop_jump_python _workshop_jump_env
    return 1
fi
if ! "$_workshop_jump_root/.local/bin/kubectl" --request-timeout=10s get --raw=/readyz; then
    unset _workshop_jump_root _workshop_jump_python _workshop_jump_env
    return 1
fi
printf '\nSelected jump-host workshop workspace; direct cluster API connection verified.\n'
unset _workshop_jump_root _workshop_jump_python _workshop_jump_env
