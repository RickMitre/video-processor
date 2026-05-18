#!/usr/bin/env bash
set -euo pipefail

DEST="${HOME}/.local/bin/vizsh"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/vizsh.py"

# check python3
if ! command -v python3 &>/dev/null; then
  echo "erro: python3 não encontrado. Instale Python 3.8+."
  exit 1
fi

PY_VER=$(python3 -c "import sys; print(sys.version_info >= (3,10))")
if [ "$PY_VER" != "True" ]; then
  echo "erro: Python 3.10+ necessário."
  exit 1
fi

mkdir -p "$(dirname "$DEST")"
cp "$SRC" "$DEST"
chmod +x "$DEST"

echo "✓ vizsh instalado em $DEST"

# add to PATH in shell rc if not already there
LINE='export PATH="$HOME/.local/bin:$PATH"'
if [[ ":${PATH}:" != *":${HOME}/.local/bin:"* ]]; then
  for RC in "$HOME/.bashrc" "$HOME/.zshrc"; do
    if [ -f "$RC" ] && ! grep -qF "$LINE" "$RC"; then
      echo "" >> "$RC"
      echo "# added by vizsh install" >> "$RC"
      echo "$LINE" >> "$RC"
      echo "✓ PATH adicionado em $RC"
    fi
  done
  export PATH="$HOME/.local/bin:$PATH"
fi
