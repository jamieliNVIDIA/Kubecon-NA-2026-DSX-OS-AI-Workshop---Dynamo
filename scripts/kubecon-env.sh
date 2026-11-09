# Source this file from zsh or bash to select the workshop kubeconfig and client.
if [ -n "${ZSH_VERSION:-}" ]; then
    _kubecon_env_path="${(%):-%x}"
elif [ -n "${BASH_VERSION:-}" ]; then
    _kubecon_env_path="${BASH_SOURCE[0]}"
else
    printf 'Source kubecon-env.sh from zsh or bash.\n' >&2
    return 1
fi
_kubecon_project_dir="$(cd -- "$(dirname -- "$_kubecon_env_path")/.." && pwd)"

if [ ! -f "$_kubecon_project_dir/.local/kubeconfig" ] || \
   [ ! -x "$_kubecon_project_dir/.local/bin/kubectl" ]; then
    printf 'Workshop kubeconfig or kubectl is missing from .local/.\n' >&2
    unset _kubecon_env_path _kubecon_project_dir
    return 1
fi
if ! "$_kubecon_project_dir/scripts/kubecon-tunnel.sh" start; then
    unset _kubecon_env_path _kubecon_project_dir
    return 1
fi

if [ "${KUBECON_WORKSHOP_ENV_ACTIVE:-0}" != 1 ]; then
    KUBECON_WORKSHOP_PREVIOUS_PATH="$PATH"
    KUBECON_WORKSHOP_PREVIOUS_KUBECONFIG="${KUBECONFIG-}"
    KUBECON_WORKSHOP_PREVIOUS_KUBECONFIG_SET="${KUBECONFIG+x}"
fi
export KUBECONFIG="$_kubecon_project_dir/.local/kubeconfig"
export PATH="$_kubecon_project_dir/.local/bin:$KUBECON_WORKSHOP_PREVIOUS_PATH"
KUBECON_WORKSHOP_ENV_ACTIVE=1

kubecon_leave() {
    export PATH="$KUBECON_WORKSHOP_PREVIOUS_PATH"
    if [ "$KUBECON_WORKSHOP_PREVIOUS_KUBECONFIG_SET" = x ]; then
        export KUBECONFIG="$KUBECON_WORKSHOP_PREVIOUS_KUBECONFIG"
    else
        unset KUBECONFIG
    fi
    unset KUBECON_WORKSHOP_PREVIOUS_PATH \
        KUBECON_WORKSHOP_PREVIOUS_KUBECONFIG \
        KUBECON_WORKSHOP_PREVIOUS_KUBECONFIG_SET \
        KUBECON_WORKSHOP_ENV_ACTIVE
    unset -f kubecon_leave
    printf 'Restored the previous Kubernetes configuration and PATH.\n'
}

printf 'Selected kubecon-workshop; kubectl connects through ubuntu@3.238.63.5.\n'
unset _kubecon_env_path _kubecon_project_dir
