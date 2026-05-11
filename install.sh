#!/bin/bash

set -e

echo "🚀 Instalando Video Processor..."
echo ""

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
DIST_DIR="$(dirname "$SCRIPT_PATH")"
APP_DIR="$HOME/video-processor-app"
BIN_DIR="$HOME/.local/bin"

echo "📁 Criando estrutura..."
mkdir -p "$APP_DIR/bin"
mkdir -p "$APP_DIR/lib"
mkdir -p "$BIN_DIR"

echo "📋 Copiando arquivos..."
cp "$DIST_DIR/lib/video-processor-cli.jar" "$APP_DIR/lib/video-processor-cli.jar"
cp "$DIST_DIR/lib/video-processor-gui.jar" "$APP_DIR/lib/video-processor-gui.jar"

echo "🔧 Criando executáveis..."

cat > "$APP_DIR/bin/video-processor" << 'SCRIPT_EOF'
#!/bin/bash
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
java -jar "$SCRIPT_DIR/../lib/video-processor-cli.jar" "$@"
SCRIPT_EOF

cat > "$APP_DIR/bin/video-processor-gui" << 'SCRIPT_EOF'
#!/bin/bash
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
java -jar "$SCRIPT_DIR/../lib/video-processor-gui.jar" "$@"
SCRIPT_EOF

chmod +x "$APP_DIR/bin/video-processor"
chmod +x "$APP_DIR/bin/video-processor-gui"

echo "🔗 Criando atalhos..."
ln -sf "$APP_DIR/bin/video-processor" "$BIN_DIR/video-processor"
ln -sf "$APP_DIR/bin/video-processor-gui" "$BIN_DIR/video-processor-gui"

# Adiciona ~/.local/bin ao PATH se ainda não estiver
BASHRC="$HOME/.bashrc"
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "" >> "$BASHRC"
    echo "# Video Processor" >> "$BASHRC"
    echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$BASHRC"
    echo ""
    echo "⚠️  Feche e abra o terminal para aplicar as alterações."
fi

echo ""
echo "✅ Instalação concluída!"
echo ""
echo "🚀 Para abrir: video-processor-gui"
echo ""
