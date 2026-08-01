#!/usr/bin/env bash
# Shared interpreter resolution for hyped-pro's bin/ launchers.
#
# Order: $HYPED_PRO_PYTHON (explicit override) > python3.12 (best-tested
# for CUDA/cuDNN wheel compatibility on older GPUs at the time this was
# written) > python3.14 > any other python3.x on $PATH with hypernix
# importable > bare "python3" as a last resort.
#
# Usage: PY="$(_hypernix_resolve_python)"
_hypernix_resolve_python() {
  if [ -n "${HYPED_PRO_PYTHON:-}" ]; then
    echo "$HYPED_PRO_PYTHON"
    return
  fi

  local cand
  for cand in python3.12 python3.14; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import hypernix" >/dev/null 2>&1; then
      echo "$cand"
      return
    fi
  done

  # Any other python3.x on PATH with hypernix importable. compgen is a
  # bash builtin (available in non-interactive scripts too) that lists
  # every command on $PATH starting with the given prefix.
  for cand in $(compgen -c python3 2>/dev/null | sort -u); do
    case "$cand" in
      python3.12|python3.14) continue ;;
    esac
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import hypernix" >/dev/null 2>&1; then
      echo "$cand"
      return
    fi
  done

  echo "python3"
}
