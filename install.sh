#!/usr/bin/env bash
# Machina Sports CLI — one-line installer
# Usage: curl -fsSL https://raw.githubusercontent.com/machina-sports/machina-cli/main/install.sh | bash
set -euo pipefail

REPO="machina-sports/machina-cli"
INSTALL_DIR="${MACHINA_INSTALL_DIR:-/usr/local/bin}"

detect_platform() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"

  case "$os" in
    Linux*)  os="linux" ;;
    Darwin*) os="darwin" ;;
    *)       echo "Unsupported OS: $os" >&2; exit 1 ;;
  esac

  case "$arch" in
    x86_64|amd64) arch="amd64" ;;
    arm64|aarch64) arch="arm64" ;;
    *)             echo "Unsupported architecture: $arch" >&2; exit 1 ;;
  esac

  echo "${os}-${arch}"
}

get_latest_version() {
  curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
    | grep '"tag_name"' | head -1 | cut -d'"' -f4
}

main() {
  local platform version url tmp

  platform="$(detect_platform)"
  version="$(get_latest_version)"

  echo "Installing machina ${version} (${platform})..."

  url="https://github.com/${REPO}/releases/download/${version}/machina-${platform}"
  tmp="$(mktemp)"

  curl -fsSL -o "$tmp" "$url"
  chmod +x "$tmp"

  if [ -w "$INSTALL_DIR" ]; then
    mv "$tmp" "${INSTALL_DIR}/machina"
  else
    echo "Need sudo to install to ${INSTALL_DIR}"
    sudo mv "$tmp" "${INSTALL_DIR}/machina"
  fi

  echo "Installed machina to ${INSTALL_DIR}/machina"
  machina version
}

main
