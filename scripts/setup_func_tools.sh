#!/usr/bin/env bash
# Install Azure Functions Core Tools v4 on Ubuntu/WSL.
# Run once: ./scripts/setup_func_tools.sh

set -euo pipefail

if command -v func &>/dev/null; then
    echo "Azure Functions Core Tools already installed: $(func --version)"
    exit 0
fi

echo "Installing Azure Functions Core Tools v4..."

# Microsoft package signing key
curl -sL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor | sudo tee /etc/apt/keyrings/microsoft.gpg >/dev/null
sudo chmod go+r /etc/apt/keyrings/microsoft.gpg

# Add Microsoft apt repo
DISTRO=$(lsb_release -cs 2>/dev/null || echo "noble")
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/ubuntu/$(lsb_release -rs)/prod ${DISTRO} main" \
    | sudo tee /etc/apt/sources.list.d/microsoft-prod.list >/dev/null

sudo apt-get update -qq
sudo apt-get install -y azure-functions-core-tools-4

echo ""
echo "Installed: func $(func --version)"
echo "Done."
