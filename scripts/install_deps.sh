#!/usr/bin/env bash
# Cross-distro bootstrap for `hypernix`. Prefers Python 3.12 if installed with hypernix,
# otherwise falls back to 3.13 or 3.14 (checking each for hypernix). Installs pip and then
# `pip install "hypernix[llama-cpp]"` into a local virtualenv at ./.venv.
#
# Supported: Ubuntu/Debian/Mint/Pop!_OS, Arch/Manjaro/EndeavourOS, Fedora/RHEL,
# openSUSE, Alpine, NixOS. Falls back to printing instructions otherwise.
#
# Usage:
#   ./scripts/install_deps.sh           # install into ./.venv
#   VENV=./myvenv ./scripts/install_deps.sh
#   NO_VENV=1 ./scripts/install_deps.sh # install into the active interpreter
set -euo pipefail

VENV="${VENV:-./.venv}"

# Function to check if hypernix is installed for a given python version
check_hypernix_installed() {
  local py_cmd="$1"
  "$py_cmd" -c "import hypernix" >/dev/null 2>&1
}

# Prefer Python 3.12 if available with hypernix; otherwise try 3.13, then 3.14, then generic python3
PY=""
for version in python3.12 python3.13 python3.14 python3; do
  if command -v "$version" >/dev/null 2>&1; then
    if check_hypernix_installed "$version"; then
      PY="$version"
      break
    fi
  fi
done

# If no version with hypernix found, just pick the first available python
if [[ -z "$PY" ]]; then
  for version in python3.12 python3.13 python3.14 python3; do
    if command -v "$version" >/dev/null 2>&1; then
      PY="$version"
      break
    fi
  done
fi

. /etc/os-release 2>/dev/null || true
ID="${ID:-unknown}"
ID_LIKE="${ID_LIKE:-}"

require_sudo() {
  if [[ $EUID -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
      SUDO="sudo"
    else
      echo "this step needs root; please rerun as root or install sudo" >&2
      exit 1
    fi
  else
    SUDO=""
  fi
}

install_system_packages() {
  case "$ID $ID_LIKE" in
    *arch*|*manjaro*|*endeavouros*)
      require_sudo
      $SUDO pacman -Syu --noconfirm --needed python python-pip llama.cpp
      ;;
    *ubuntu*|*debian*|*mint*|*pop*|*elementary*)
      require_sudo
      $SUDO apt-get update
      # Try to install Python 3.12 first (preferred), but allow fallback to system default
      if ! apt-cache show python3.12 >/dev/null 2>&1; then
        $SUDO apt-get install -y software-properties-common
        $SUDO add-apt-repository -y ppa:deadsnakes/ppa || true
        $SUDO apt-get update
      fi
      # Install 3.12 if available, otherwise use system python3
      if apt-cache show python3.12 >/dev/null 2>&1; then
        $SUDO apt-get install -y python3.12 python3.12-venv python3-pip
      else
        $SUDO apt-get install -y python3 python3-venv python3-pip
      fi
      ;;
    *fedora*|*rhel*|*almalinux*|*rocky*|*centos*)
      require_sudo
      # Try 3.12 first, fall back to system python3
      $SUDO dnf install -y python3.12 python3.12-pip || $SUDO dnf install -y python3 python3-pip
      ;;
    *opensuse*|*suse*|*sles*)
      require_sudo
      # Try 3.12 first, fall back to system python3
      $SUDO zypper install -y python312 python312-pip || $SUDO zypper install -y python3 python3-pip
      ;;
    *alpine*)
      require_sudo
      $SUDO apk add --no-cache python3 py3-pip bash
      PY=python3
      ;;
    *nixos*)
      echo "NixOS detected. Run inside a devshell:" >&2
      echo "  nix-shell -p python312 gcc -- --run 'bash scripts/install_deps.sh'" >&2
      ;;
    *)
      echo "Unrecognized distro ($ID). Ensure 'python3.12', 'python3.13', 'python3.14', or 'python3' is on PATH, then rerun." >&2
      ;;
  esac
}

main() {
  install_system_packages

  # Re-detect Python after system package installation
  if [[ -z "$PY" ]] || ! command -v "$PY" >/dev/null 2>&1; then
    # Fall back to a generic python3 binary if preferred version isn't available.
    PY=""
    # First try to find a version with hypernix already installed
    for version in python3.12 python3.13 python3.14 python3; do
      if command -v "$version" >/dev/null 2>&1; then
        if check_hypernix_installed "$version"; then
          PY="$version"
          break
        fi
      fi
    done
    # If no version with hypernix found, just pick the first available python
    if [[ -z "$PY" ]]; then
      for version in python3.12 python3.13 python3.14 python3; do
        if command -v "$version" >/dev/null 2>&1; then
          PY="$version"
          break
        fi
      done
    fi
    [[ -n "$PY" ]] || { echo "no python3 on PATH" >&2; exit 1; }
  fi

  if [[ -z "${NO_VENV:-}" ]]; then
    "$PY" -m venv "$VENV"
    # shellcheck disable=SC1091
    . "$VENV/bin/activate"
  fi

  python -m pip install --upgrade pip
  python -m pip install "hypernix[llama-cpp]"

  echo
  echo "hypernix installed. Verify with:"
  [[ -n "${NO_VENV:-}" ]] || echo "  source $VENV/bin/activate"
  echo "  hypernix doctor"
}

main "$@"
