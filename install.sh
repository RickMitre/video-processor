#!/bin/bash
set -e

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
DIST_DIR="$(dirname "$SCRIPT_PATH")"

echo "🚀 Instalando ferramentas..."
echo ""

echo "── video-processor ──────────────────────"
bash "$DIST_DIR/video-processor/install.sh"
echo ""

echo "── vizsh ────────────────────────────────"
bash "$DIST_DIR/vizsh/install.sh"
echo ""

echo "✅ Tudo instalado!"
echo ""
echo "  video-processor-gui     → interface gráfica de processamento de vídeo"
echo "  vizsh arquivo.sh        → visualizador de cenas FFmpeg"
echo ""
