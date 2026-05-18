#!/usr/bin/env python3
"""vizsh — visualizador de cenas para scripts .sh de geração de vídeo."""

import json
import queue
import re
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

PORT = 9000


def _find_noto_sans() -> bytes | None:
    """Return bytes of the system Noto Sans Regular font (same file libass uses)."""
    # Ask fontconfig first
    try:
        r = subprocess.run(
            ["fc-match", "Noto Sans:style=Regular", "--format=%{file}"],
            capture_output=True, text=True, timeout=5,
        )
        p = Path(r.stdout.strip())
        if p.is_file():
            return p.read_bytes()
    except Exception:
        pass
    # Fallback known paths
    for candidate in [
        "/usr/share/fonts/google-noto-vf/NotoSans[wght].ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/noto-sans/NotoSans-Regular.ttf",
    ]:
        p = Path(candidate)
        if p.is_file():
            return p.read_bytes()
    return None


_FONT_BYTES = _find_noto_sans()
CW, CH = 1920, 1080

SCENE_BLOCK_RE = re.compile(
    r"cat << 'EOF' \| head --bytes=-1 > (v-\d+-([a-z]))\.ass\n(.*?)\nEOF",
    re.DOTALL,
)


# ─── parser ────────────────────────────────────────────────────────────────────

def _split_csv(line):
    return [p.strip() for p in line.split(",")]


def _parse_style(ass):
    m = re.search(r"\[V4\+ Styles\](.*?)(?=\n\s*\[|\Z)", ass, re.DOTALL)
    if not m:
        return {}
    block = m.group(1)
    fmt = re.search(r"^\s*Format:\s*(.+)$", block, re.MULTILINE)
    sty = re.search(r"^\s*Style:\s*(.+)$", block, re.MULTILINE)
    if not fmt or not sty:
        return {}
    return dict(zip(_split_csv(fmt.group(1)), _split_csv(sty.group(1))))


def _parse_dialogue(ass):
    m = re.search(r"\[Events\](.*?)\Z", ass, re.DOTALL)
    if not m:
        return None
    block = m.group(1)
    fmt = re.search(r"^\s*Format:\s*(.+)$", block, re.MULTILINE)
    dlg = re.search(r"^\s*Dialogue:\s*(.+)$", block, re.MULTILINE)
    if not fmt or not dlg:
        return None
    fields = _split_csv(fmt.group(1))
    parts = dlg.group(1).split(",", len(fields) - 1)
    if len(parts) != len(fields):
        return None
    return {f: v.strip() for f, v in zip(fields, parts)}


def _color_name(val):
    return "White" if "FFFFFF" in val.upper() else "Black"


def _extract_text(t):
    return re.sub(r"\{[^}]*\}", "", t).strip()


def _extract_pos(t):
    m = re.search(r"\\pos\(\s*(\d+)\s*,\s*(\d+)\s*\)", t)
    return [int(m.group(1)), int(m.group(2))] if m else None


def parse_scene(basename, letter, ass, chunk):
    style = _parse_style(ass)
    dlg   = _parse_dialogue(ass)

    ml = int(style.get("MarginL", "0") or "0")
    mr = int(style.get("MarginR", "0") or "0")
    margin   = mr if mr else ml
    fontsize = int(style.get("Fontsize", "0") or "0") if style else 0
    color    = _color_name(style.get("PrimaryColour", "&H00000000")) if style else "Black"

    pos  = None
    text = ""
    if dlg and "Text" in dlg:
        pos  = _extract_pos(dlg["Text"])
        text = _extract_text(dlg["Text"])

    # all image overlays (image-1, image-2, …)
    image_files = re.findall(rf"-i ({re.escape(basename)}-image-\d+\.\w+)", chunk)
    bg_m        = re.search(rf"-i ({re.escape(basename)}-background\.(\w+))", chunk)

    # overlay coordinates from e.g. overlay=100:200  or  [x]overlay=100:200[y]
    def _overlay_pos(img_file: str) -> list[int]:
        # look for the overlay call that comes right after this specific image label
        m = re.search(r"overlay=(\d+):(\d+)", chunk)
        if m:
            return [int(m.group(1)), int(m.group(2))]
        return [0, 0]

    images = [
        {"file": f, "pos": _overlay_pos(f)}
        for f in image_files
    ]

    return {
        "letter":          letter,
        "basename":        basename,
        "pos":             pos,
        "fontsize":        fontsize,
        "margin":          margin,
        "color":           color,
        "text":            text,
        "images":          images,
        "has_image":       bool(images),
        "image_file":      images[0]["file"] if images else None,
        "image_pos":       images[0]["pos"]  if images else [0, 0],
        "background_mp4":  bool(bg_m and bg_m.group(2).lower() == "mp4"),
        "background_file": bg_m.group(1) if bg_m else None,
    }


def parse_sh(sh_path):
    content = Path(sh_path).read_text(encoding="utf-8")
    matches = list(SCENE_BLOCK_RE.finditer(content))
    scenes  = []
    for i, m in enumerate(matches):
        basename, letter, ass = m.group(1), m.group(2), m.group(3)
        chunk_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        scenes.append(parse_scene(basename, letter, ass, content[m.end():chunk_end]))
    return scenes


# ─── HTML app ──────────────────────────────────────────────────────────────────

HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>vizsh — __FILENAME__</title>
<style>
@font-face {
  font-family: 'Noto Sans';
  src: url('/noto-sans.ttf') format('truetype');
  font-weight: 100 900;
  font-style: normal;
  font-display: block;
}
:root {
  --bg:     #0d1017;
  --surface:#141820;
  --panel:  #161c26;
  --border: #232b38;
  --text:   #dde3ee;
  --muted:  #6b7893;
  --accent: #5b9cf6;
  --green:  #4ec994;
  --handle: #5b9cf6;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; overflow: hidden; background: var(--bg); color: var(--text);
  font-family: ui-sans-serif, system-ui, sans-serif; }
body { display: flex; flex-direction: column; }

/* ── header ── */
header {
  display: flex; align-items: center; gap: 12px;
  padding: 0 16px; height: 40px; flex-shrink: 0;
  background: var(--surface); border-bottom: 1px solid var(--border);
  font-family: ui-monospace, monospace; font-size: 12px;
}
.logo { font-weight: 700; letter-spacing: .08em; color: var(--accent); }
.hfile { color: var(--muted); }
.spacer { flex: 1; }
.coords { color: var(--muted); min-width: 90px; text-align: right; font-variant-numeric: tabular-nums; }

/* ── tabs ── */
.tabs {
  display: flex; gap: 3px; padding: 6px 14px; flex-shrink: 0;
  background: var(--surface); border-bottom: 1px solid var(--border);
}
.tab {
  padding: 4px 13px; border-radius: 5px; cursor: pointer;
  border: 1px solid transparent; background: transparent;
  color: var(--muted); font-family: ui-monospace, monospace; font-size: 13px;
  transition: color .1s;
}
.tab:hover { color: var(--text); }
.tab.active { background: var(--bg); color: var(--text); border-color: var(--border); }
.tab[data-mp4]::after { content: '▶'; font-size: 8px; margin-left: 4px; color: var(--green); vertical-align: middle; }
.tab[data-img]::after { content: '⊞'; font-size: 10px; margin-left: 4px; color: var(--accent); vertical-align: middle; }

/* ── workspace ── */
.workspace { flex: 1; display: flex; min-height: 0; }

/* ── canvas area ── */
.canvas-wrap {
  flex: 1; display: flex; align-items: center; justify-content: center;
  padding: 16px; overflow: hidden; min-width: 0;
}
#canvasOuter {
  position: relative; overflow: hidden; flex-shrink: 0;
  border: 1px solid var(--border);
  box-shadow: 0 0 0 1px rgba(91,156,246,.15), 0 8px 32px rgba(0,0,0,.6);
}
#canvasScaler {
  position: relative; width: 1920px; height: 1080px;
  transform-origin: top left; overflow: hidden;
  background: #12161f;
  background-image:
    linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
  background-size: 96px 54px;
}
#canvasScaler.is-mp4 {
  background-image: none;
  background: linear-gradient(140deg, #141e2e 0%, #1e1028 60%, #0e1822 100%);
}

/* bg media */
.bg-media {
  position: absolute; inset: 0; width: 1920px; height: 1080px;
  object-fit: cover; display: none; pointer-events: none;
}
.bg-media.active { display: block; }

/* mp4 badge */
#mp4Badge {
  position: absolute; top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  font-family: ui-monospace, monospace; font-size: 22px;
  color: rgba(255,255,255,.22); letter-spacing: .25em;
  pointer-events: none; display: none;
}
#mp4Badge.visible { display: block; }

/* centerlines */
.cline {
  position: absolute; pointer-events: none; z-index: 50;
  border-color: rgba(255,255,255,.1); border-style: dashed;
}
.cline-h { left: 0; right: 0; top: 540px; border-top-width: 1px; border-bottom: 0; }
.cline-v { top: 0; bottom: 0; left: 960px; border-left-width: 1px; border-right: 0; }

/* ── image overlay ── */
#overlayWrap {
  position: absolute; cursor: move; z-index: 10;
  display: none; user-select: none;
}
#overlayWrap.visible { display: block; }
#overlayWrap.selected { outline: 2px solid rgba(91,156,246,.7); outline-offset: 2px; }
#overlayImg { display: block; max-width: none; pointer-events: none; user-select: none; }
#overlayPlaceholder {
  position: absolute; inset: 0;
  border: 2px dashed rgba(91,156,246,.5);
  background: rgba(91,156,246,.06);
  display: flex; align-items: center; justify-content: center;
  font-family: ui-monospace, monospace; font-size: 13px; color: var(--accent);
  min-width: 200px; min-height: 120px;
}

/* ── text object ── */
#textWrap {
  position: absolute; cursor: move; z-index: 20;
  transform: translate(-50%, -50%);
  display: none; user-select: none;
}
#textWrap.visible { display: block; }
#textWrap.selected #textInner { outline: 2px solid rgba(91,156,246,.7); outline-offset: 5px; }
#textInner {
  font-family: 'Noto Sans', 'Noto Sans', sans-serif;
  text-align: center; line-height: 1.18;
  white-space: normal; overflow-wrap: normal;
  pointer-events: none;
}
#textInner.black { color: #000; }
#textInner.white { color: #fff; }

/* ── handles ── */
.hnd {
  position: absolute; z-index: 30;
  width: 14px; height: 14px;
  background: var(--handle); border: 2px solid var(--bg);
  border-radius: 3px; display: none;
}
#textWrap.selected .hnd { display: block; }
#overlayWrap.selected .hnd { display: block; }
#hndRight  { right: -9px; top: 50%; transform: translateY(-50%); cursor: ew-resize; }
#hndBottom { bottom: -9px; left: 50%; transform: translateX(-50%); cursor: ns-resize; }
#hndImgRight { right: -9px; top: 50%; transform: translateY(-50%); cursor: ew-resize; }

/* ── panel ── */
aside {
  width: 300px; flex-shrink: 0;
  background: var(--panel); border-left: 1px solid var(--border);
  display: flex; flex-direction: column; overflow: hidden;
}
.panel-scroll { flex: 1; overflow-y: auto; padding: 12px 14px; }
.panel-scroll::-webkit-scrollbar { width: 6px; }
.panel-scroll::-webkit-scrollbar-track { background: transparent; }
.panel-scroll::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

.sec { font-family: ui-monospace, monospace; font-size: 10px; text-transform: uppercase;
  letter-spacing: .12em; color: var(--muted); padding: 12px 0 6px; font-weight: 600; }
.sec:first-child { padding-top: 0; }
.frow { display: flex; align-items: center; gap: 8px; padding: 5px 0;
  border-bottom: 1px solid var(--border); }
.frow label { flex: 0 0 62px; font-family: ui-monospace, monospace; font-size: 11px; color: var(--muted); }
.frow input[type=number], .frow input[type=text] {
  flex: 1; background: var(--bg); border: 1px solid var(--border);
  color: var(--text); padding: 4px 7px;
  font-family: ui-monospace, monospace; font-size: 12px; border-radius: 4px;
  -moz-appearance: textfield;
}
.frow input::-webkit-outer-spin-button,
.frow input::-webkit-inner-spin-button { -webkit-appearance: none; }
.frow input:focus { outline: 1px solid var(--accent); border-color: var(--accent); }
.frow span { font-family: ui-monospace, monospace; font-size: 12px; color: var(--text); }
.ctoggle { display: flex; gap: 4px; }
.ctoggle button {
  padding: 3px 11px; border-radius: 4px; border: 1px solid var(--border);
  background: transparent; color: var(--muted); cursor: pointer;
  font-size: 11px; font-family: ui-monospace, monospace;
}
.ctoggle button.active { background: var(--accent); color: #000; border-color: var(--accent); font-weight: 600; }
.txt-area {
  width: 100%; margin-top: 6px;
  background: var(--bg); border: 1px solid var(--border); color: var(--text);
  padding: 7px; font-family: ui-monospace, monospace; font-size: 12px;
  border-radius: 4px; resize: vertical; line-height: 1.5;
}
.txt-area:focus { outline: 1px solid var(--accent); }

/* ── footer ── */
.panel-footer {
  padding: 12px 14px; border-top: 1px solid var(--border);
  background: var(--surface);
}
.md-box {
  background: var(--bg); border: 1px solid var(--border); border-radius: 4px;
  padding: 9px 10px; font-family: ui-monospace, monospace; font-size: 11px;
  white-space: pre-wrap; word-break: break-all; color: var(--text);
  min-height: 36px; margin-bottom: 8px; line-height: 1.6;
}
.copy-btn {
  width: 100%; padding: 7px; background: var(--accent); color: #000;
  border: none; border-radius: 4px; cursor: pointer;
  font-weight: 700; font-size: 12px; font-family: ui-monospace, monospace;
  transition: opacity .15s;
}
.copy-btn:hover { opacity: .85; }
.copy-btn.ok { background: var(--green); }
</style>
</head>
<body>
<header>
  <span class="logo">vizsh</span>
  <span class="hfile">__FILENAME__</span>
  <span class="spacer"></span>
  <span class="coords" id="coords">—</span>
</header>
<div class="tabs" id="tabs"></div>
<div class="workspace">
  <div class="canvas-wrap" id="canvasWrap">
    <div id="canvasOuter">
      <div id="canvasScaler">
        <img  id="bgImg"   class="bg-media" draggable="false">
        <video id="bgVideo" class="bg-media" autoplay loop muted playsinline preload="auto"></video>
        <div id="mp4Badge">BACKGROUND = mp4</div>
        <div id="overlayWrap">
          <img id="overlayImg" draggable="false">
          <div id="overlayPlaceholder"></div>
          <div id="hndImgRight" class="hnd"></div>
        </div>
        <div id="textWrap">
          <div id="textInner"></div>
          <div id="hndRight"  class="hnd"></div>
          <div id="hndBottom" class="hnd"></div>
        </div>
        <div class="cline cline-h"></div>
        <div class="cline cline-v"></div>
      </div>
    </div>
  </div>
  <aside>
    <div class="panel-scroll" id="panelScroll"></div>
    <div class="panel-footer">
      <div class="sec" style="padding-top:0">Saída .md</div>
      <div class="md-box" id="mdBox"></div>
      <button class="copy-btn" id="copyBtn">Copiar</button>
    </div>
  </aside>
</div>

<script>
// reload when server restarts (works even from disk cache)
const PAGE_VERSION = __VERSION__;
fetch('/version', {cache: 'no-store'}).then(r => r.text()).then(v => {
  if (v.trim() !== String(PAGE_VERSION)) location.href = '/?v=' + v.trim();
}).catch(() => {});

// auto-reload when .sh file changes on disk
const _es = new EventSource('/events');
_es.onmessage = () => location.reload();

const SCENES = __SCENES__;
const CW = 1920, CH = 1080;
// libass renders ASS Fontsize at ~0.651× the CSS px value (empirically measured)
const LIBASS_SCALE = __LIBASS_SCALE__;

// init mutable per-scene state not from parser
SCENES.forEach(s => {
  // image_pos comes from parser (overlay coords); fallback [0,0]
  if (!s.image_pos) s.image_pos = [0, 0];
  s.image_w = null;
});

let activeIdx = 0;
let scale = 1;
let selected = null; // 'text' | 'image' | null
let dragMode = null;
let dragOrigin = null;

// DOM refs
const $  = id => document.getElementById(id);
const canvasWrap   = $('canvasWrap');
const canvasOuter  = $('canvasOuter');
const canvasScaler = $('canvasScaler');
const bgImg        = $('bgImg');
const bgVideo      = $('bgVideo');
const mp4Badge     = $('mp4Badge');
const overlayWrap  = $('overlayWrap');
const overlayImg   = $('overlayImg');
const overlayPH    = $('overlayPlaceholder');
const hndImgRight  = $('hndImgRight');
const textWrap     = $('textWrap');
const textInner    = $('textInner');
const hndRight     = $('hndRight');
const hndBottom    = $('hndBottom');
const panelScroll  = $('panelScroll');
const mdBox        = $('mdBox');
const copyBtn      = $('copyBtn');
const coordsEl     = $('coords');
const tabsEl       = $('tabs');

// ── scale ───────────────────────────────────────────────────────────────────
function fitCanvas() {
  const pw = canvasWrap.clientWidth  - 32;
  const ph = canvasWrap.clientHeight - 32;
  scale = Math.min(pw / CW, ph / CH, 1);
  const w = Math.floor(CW * scale);
  const h = Math.floor(CH * scale);
  canvasOuter.style.width  = w + 'px';
  canvasOuter.style.height = h + 'px';
  canvasScaler.style.transform = `scale(${scale})`;
}
window.addEventListener('resize', fitCanvas);

// ── coords ──────────────────────────────────────────────────────────────────
function screenToCanvas(cx, cy) {
  const r = canvasScaler.getBoundingClientRect();
  return [Math.round((cx - r.left) / scale), Math.round((cy - r.top) / scale)];
}

// ── render ───────────────────────────────────────────────────────────────────
function renderAll() {
  renderTabs();
  renderScene();
  renderPanel();
}

function renderTabs() {
  tabsEl.innerHTML = '';
  SCENES.forEach((s, i) => {
    const b = document.createElement('button');
    b.className = 'tab' + (i === activeIdx ? ' active' : '');
    b.textContent = s.letter;
    if (s.background_mp4) b.dataset.mp4 = '1';
    if (s.has_image)      b.dataset.img  = '1';
    b.onclick = () => { activeIdx = i; selected = null; renderAll(); };
    tabsEl.appendChild(b);
  });
}

function renderScene() {
  const s = SCENES[activeIdx];

  // background
  canvasScaler.classList.toggle('is-mp4', !!s.background_mp4);
  mp4Badge.classList.toggle('visible', !!s.background_mp4);

  if (s.background_mp4) {
    bgImg.classList.remove('active');
    const src = (s.background_file || s.basename + '-background.mp4');
    if (bgVideo.dataset.loaded !== src) {
      bgVideo.dataset.loaded = src;
      bgVideo.src = src;
      bgVideo.load();
      bgVideo.play().catch(() => {});
    }
    bgVideo.classList.add('active');
  } else {
    bgVideo.classList.remove('active');
    const src = (s.background_file || s.basename + '-background.webp');
    if (bgImg.dataset.loaded !== src) {
      bgImg.dataset.loaded = src;
      bgImg.src = src;
    }
    bgImg.classList.add('active');
  }

  // primary image overlay (draggable)
  if (s.has_image) {
    overlayWrap.classList.add('visible');
    overlayWrap.classList.toggle('selected', selected === 'image');
    overlayWrap.style.left = s.image_pos[0] + 'px';
    overlayWrap.style.top  = s.image_pos[1] + 'px';

    const imgSrc = s.image_file || s.basename + '-image-1.webp';
    if (overlayImg.dataset.loaded !== imgSrc) {
      overlayImg.dataset.loaded = imgSrc;
      overlayImg.src = imgSrc;
      overlayImg.onload = () => {
        overlayPH.style.display = 'none';
        if (!s.image_w) {
          s.image_w = overlayImg.naturalWidth;
          overlayImg.style.width = '';
        }
      };
      overlayImg.onerror = () => {
        overlayImg.style.display = 'none';
        overlayPH.style.display = '';
        overlayPH.textContent = '⊞  ' + (s.image_file || s.basename + '-image-1');
        const ow = s.image_w || 400, oh = Math.round(ow * 9/16);
        overlayPH.style.width  = ow + 'px';
        overlayPH.style.height = oh + 'px';
      };
    }
    if (s.image_w) { overlayImg.style.width = s.image_w + 'px'; overlayImg.style.display = ''; }
    hndImgRight.style.display = selected === 'image' ? '' : 'none';
  } else {
    overlayWrap.classList.remove('visible', 'selected');
  }

  // extra images (image-2, image-3, …) — static, not draggable
  canvasScaler.querySelectorAll('.extra-img').forEach(el => el.remove());
  if (s.images && s.images.length > 1) {
    s.images.slice(1).forEach(img => {
      const el = document.createElement('img');
      el.className = 'extra-img';
      el.draggable = false;
      el.style.cssText = `position:absolute;left:${img.pos[0]}px;top:${img.pos[1]}px;pointer-events:none;`;
      el.src = img.file;
      canvasScaler.appendChild(el);
    });
  }

  // text
  if (s.pos && s.text) {
    textWrap.classList.add('visible');
    textWrap.classList.toggle('selected', selected === 'text');
    textWrap.style.left  = s.pos[0] + 'px';
    textWrap.style.top   = s.pos[1] + 'px';
    textWrap.style.width = ((s.pos ? Math.min(2 * s.pos[0], CW) : CW) * LIBASS_SCALE) + 'px';
    textInner.style.fontSize = (s.fontsize * LIBASS_SCALE) + 'px';
    textInner.className  = s.color.toLowerCase();
    textInner.textContent = s.text;
    hndRight.style.display  = selected === 'text' ? '' : 'none';
    hndBottom.style.display = selected === 'text' ? '' : 'none';
  } else {
    textWrap.classList.remove('visible', 'selected');
  }
}

// ── panel ───────────────────────────────────────────────────────────────────
function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function frow(lbl, id, val, type = 'number') {
  return `<div class="frow"><label>${lbl}</label><input id="${id}" type="${type}" value="${esc(val)}"></div>`;
}

function renderPanel() {
  const s = SCENES[activeIdx];
  let h = '';

  if (selected === 'text' && s.pos) {
    h += `<div class="sec">TEXT</div>`;
    h += frow('x',        'fX',  s.pos[0]);
    h += frow('y',        'fY',  s.pos[1]);
    h += frow('margin',   'fM',  s.margin);
    h += frow('fontsize', 'fF',  s.fontsize);
    h += `<div class="frow"><label>cor</label>
      <div class="ctoggle">
        <button data-color="Black" class="${s.color==='Black'?'active':''}">Black</button>
        <button data-color="White" class="${s.color==='White'?'active':''}">White</button>
      </div></div>`;
    h += `<div class="frow" style="border:0"><label>texto</label></div>
      <textarea class="txt-area" id="fTxt" rows="4">${esc(s.text)}</textarea>`;

  } else if (selected === 'image' && s.has_image) {
    h += `<div class="sec">IMAGE</div>`;
    h += frow('x', 'fIX', s.image_pos[0]);
    h += frow('y', 'fIY', s.image_pos[1]);
    if (s.image_w) h += `<div class="frow"><label>w</label><input id="fIW" type="number" value="${s.image_w}"></div>`;

  } else {
    h += `<div class="sec">Cena ${s.letter.toUpperCase()}</div>`;
    const info = [
      ['background', s.background_mp4 ? 'mp4' : 'webp'],
      ['imagem', s.has_image ? s.image_file || (s.basename+'-image-1') : '—'],
    ];
    if (s.pos) {
      info.push(['x', s.pos[0]], ['y', s.pos[1]]);
      info.push(['margin', s.margin], ['fontsize', s.fontsize], ['cor', s.color]);
    }
    h += info.map(([k,v]) =>
      `<div class="frow"><label>${k}</label><span>${esc(String(v))}</span></div>`).join('');
    if (s.pos) {
      h += `<div class="sec">Editar</div>`;
      h += frow('x',        'fX',  s.pos[0]);
      h += frow('y',        'fY',  s.pos[1]);
      h += frow('margin',   'fM',  s.margin);
      h += frow('fontsize', 'fF',  s.fontsize);
      h += `<div class="frow"><label>cor</label>
        <div class="ctoggle">
          <button data-color="Black" class="${s.color==='Black'?'active':''}">Black</button>
          <button data-color="White" class="${s.color==='White'?'active':''}">White</button>
        </div></div>`;
      h += `<div class="frow" style="border:0"><label>texto</label></div>
        <textarea class="txt-area" id="fTxt" rows="4">${esc(s.text)}</textarea>`;
    }
  }

  panelScroll.innerHTML = h;

  // wire inputs
  const wire = (id, fn) => { const el = $(id); if (el) el.addEventListener('input', e => { _pushUndo(); fn(e.target.value); refreshObj(); updateMd(); updatePanelFields(s); }); };
  wire('fX',  v => s.pos && (s.pos[0] = +v|0));
  wire('fY',  v => s.pos && (s.pos[1] = +v|0));
  wire('fM',  v => { s.margin   = Math.max(1, +v|0); });
  wire('fF',  v => { s.fontsize = Math.max(1, +v|0); });
  wire('fTxt',v => { s.text = v; });
  wire('fIX', v => { s.image_pos[0] = +v|0; });
  wire('fIY', v => { s.image_pos[1] = +v|0; });
  wire('fIW', v => { s.image_w = Math.max(10, +v|0); overlayImg.style.width = s.image_w + 'px'; });

  panelScroll.querySelectorAll('[data-color]').forEach(btn =>
    btn.addEventListener('click', () => {
      s.color = btn.dataset.color;
      renderAll();
    })
  );

  updateMd();
}

function getMdLines(s) {
  const lines = [];
  if (s.has_image)      lines.push('IMAGE=');
  if (s.background_mp4) lines.push('BACKGROUND=mp4');
  if (s.pos && s.text)
    lines.push(`TEXT=${s.pos[0]},${s.pos[1]},${s.margin},${s.color},${s.fontsize},${s.text}`);
  return lines;
}

function updateMd() {
  const lines = getMdLines(SCENES[activeIdx]);
  mdBox.textContent = lines.length ? lines.join('\n') : '(cena sem saída)';
}

function updatePanelFields(s) {
  const setv = (id, v) => { const el = $(id); if (el && document.activeElement !== el) el.value = v; };
  setv('fX',  s.pos?.[0] ?? '');
  setv('fY',  s.pos?.[1] ?? '');
  setv('fM',  s.margin);
  setv('fF',  s.fontsize);
  setv('fIX', s.image_pos?.[0] ?? '');
  setv('fIY', s.image_pos?.[1] ?? '');
  setv('fIW', s.image_w ?? '');
}

function refreshObj() {
  const s = SCENES[activeIdx];
  if (s.pos && s.text) {
    textWrap.style.left   = s.pos[0] + 'px';
    textWrap.style.top    = s.pos[1] + 'px';
    textWrap.style.width  = ((s.pos ? Math.min(2 * s.pos[0], CW) : CW) * LIBASS_SCALE) + 'px';
    textInner.style.fontSize = (s.fontsize * LIBASS_SCALE) + 'px';
    textInner.className   = s.color.toLowerCase();
    textInner.textContent = s.text;
  }
  if (s.has_image) {
    overlayWrap.style.left = s.image_pos[0] + 'px';
    overlayWrap.style.top  = s.image_pos[1] + 'px';
    if (s.image_w) overlayImg.style.width = s.image_w + 'px';
  }
}

// ── drag ─────────────────────────────────────────────────────────────────────
// ── undo ─────────────────────────────────────────────────────────────────────
const _undo = [];
function _pushUndo() {
  _undo.push({ idx: activeIdx, snap: JSON.parse(JSON.stringify(SCENES[activeIdx])) });
  if (_undo.length > 50) _undo.shift();
}

function startDrag(e, mode) {
  _pushUndo();
  e.preventDefault(); e.stopPropagation();
  try { e.target.setPointerCapture(e.pointerId); } catch(_) {}
  const s = SCENES[activeIdx];
  dragMode   = mode;
  dragOrigin = {
    cx: e.clientX, cy: e.clientY,
    pos:      s.pos      ? [...s.pos]      : null,
    margin:   s.margin,
    fontsize: s.fontsize,
    ipos:     s.image_pos ? [...s.image_pos] : [0,0],
    iw:       s.image_w  || overlayImg.naturalWidth || 400,
  };
}

document.addEventListener('pointermove', e => {
  if (!dragMode || !dragOrigin) return;
  const s  = SCENES[activeIdx];
  const dx = (e.clientX - dragOrigin.cx) / scale;
  const dy = (e.clientY - dragOrigin.cy) / scale;

  switch (dragMode) {
    case 'text':
      if (dragOrigin.pos)
        s.pos = [Math.round(dragOrigin.pos[0] + dx), Math.round(dragOrigin.pos[1] + dy)];
      break;
    case 'image':
      s.image_pos = [Math.round(dragOrigin.ipos[0] + dx), Math.round(dragOrigin.ipos[1] + dy)];
      break;
    case 'hnd-right': {
      // drag right edge → shift pos_x so the visual wrap edge follows the mouse
      // for left-half text (wrap = 2*pos_x), right edge = pos_x*(1+LIBASS_SCALE)
      // for right-half text (wrap = CW), right edge = pos_x + CW*LIBASS_SCALE/2
      const factor = dragOrigin.pos[0] < CW / 2 ? 1 / (1 + LIBASS_SCALE) : 1;
      s.pos[0] = Math.max(50, Math.min(CW - 50, Math.round(dragOrigin.pos[0] + dx * factor)));
      break;
    }
    case 'hnd-bottom':
      s.fontsize = Math.max(8, Math.round(dragOrigin.fontsize + dy));
      break;
    case 'hnd-img-right':
      s.image_w = Math.max(50, Math.round(dragOrigin.iw + dx));
      overlayImg.style.width = s.image_w + 'px';
      break;
  }
  refreshObj();
  updatePanelFields(s);
  updateMd();
});

document.addEventListener('pointerup', () => { dragMode = null; dragOrigin = null; });

// pointer targets
textWrap.addEventListener('pointerdown', e => {
  if (e.target === hndRight)  { startDrag(e, 'hnd-right');  return; }
  if (e.target === hndBottom) { startDrag(e, 'hnd-bottom'); return; }
  if (selected !== 'text') { selected = 'text'; renderScene(); renderPanel(); }
  startDrag(e, 'text');
});

overlayWrap.addEventListener('pointerdown', e => {
  if (e.target === hndImgRight) { startDrag(e, 'hnd-img-right'); return; }
  if (selected !== 'image') { selected = 'image'; renderScene(); renderPanel(); }
  startDrag(e, 'image');
});

canvasScaler.addEventListener('pointerdown', e => {
  if (e.target === canvasScaler || e.target === bgImg || e.target === bgVideo) {
    if (selected !== null) { selected = null; renderScene(); renderPanel(); }
  }
});

// scroll = fontsize
textWrap.addEventListener('wheel', e => {
  e.preventDefault();
  const s = SCENES[activeIdx];
  s.fontsize = Math.max(8, s.fontsize - Math.sign(e.deltaY) * 5);
  refreshObj();
  updatePanelFields(s);
  updateMd();
}, { passive: false });

// keyboard arrows
document.addEventListener('keydown', e => {
  const inField = ['INPUT','TEXTAREA'].includes(document.activeElement?.tagName);

  // Ctrl+Z — undo
  if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
    e.preventDefault();
    if (_undo.length) {
      const prev = _undo.pop();
      if (prev.idx === activeIdx) {
        Object.assign(SCENES[activeIdx], prev.snap);
        renderAll();
      }
    }
    return;
  }

  if (inField || !selected) return;
  const d = { ArrowLeft:[-1,0], ArrowRight:[1,0], ArrowUp:[0,-1], ArrowDown:[0,1] }[e.key];
  if (!d) return;
  e.preventDefault();
  _pushUndo();
  const step = e.shiftKey ? 10 : 1;
  const s = SCENES[activeIdx];
  if (selected === 'text' && s.pos) {
    s.pos[0] += d[0] * step;
    s.pos[1] += d[1] * step;
  } else if (selected === 'image') {
    s.image_pos[0] += d[0] * step;
    s.image_pos[1] += d[1] * step;
  }
  refreshObj();
  updatePanelFields(s);
  updateMd();
});

// copy button
copyBtn.addEventListener('click', () => {
  const txt = getMdLines(SCENES[activeIdx]).join('\n');
  navigator.clipboard.writeText(txt).then(() => {
    copyBtn.textContent = 'Copiado!';
    copyBtn.classList.add('ok');
    setTimeout(() => { copyBtn.textContent = 'Copiar'; copyBtn.classList.remove('ok'); }, 1600);
  });
});

// mouse coords display
canvasScaler.addEventListener('mousemove', e => {
  const [cx, cy] = screenToCanvas(e.clientX, e.clientY);
  coordsEl.textContent = `${cx}, ${cy}`;
});
canvasScaler.addEventListener('mouseleave', () => { coordsEl.textContent = '—'; });

// ── init ─────────────────────────────────────────────────────────────────────
fitCanvas();
renderAll();
</script>
</body>
</html>
"""


# ─── server ────────────────────────────────────────────────────────────────────

MIME = {".webp":"image/webp",".png":"image/png",".jpg":"image/jpeg",
        ".jpeg":"image/jpeg",".mp4":"video/mp4",".webm":"video/webm",
        ".mp3":"audio/mpeg"}


def build_html(scenes, filename, version, libass_scale):
    return (HTML
            .replace("__FILENAME__", filename)
            .replace("__VERSION__", str(version))
            .replace("__LIBASS_SCALE__", str(libass_scale))
            .replace("__SCENES__", json.dumps(scenes, ensure_ascii=False)))


def make_handler(state: dict, asset_dir: Path, broadcaster: _SSEBroadcaster):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            p  = unquote(self.path).split("?")[0]
            qs = self.path.split("?", 1)[1] if "?" in self.path else ""

            if p == "/version":
                body = str(state['version']).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if p == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                q = broadcaster.connect()
                try:
                    while True:
                        try:
                            msg = q.get(timeout=15)
                            self.wfile.write(f"data: {msg}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                except Exception:
                    pass
                finally:
                    broadcaster.disconnect(q)
                return

            if p in ("/", "/index.html"):
                if "v=" not in qs:
                    self.send_response(302)
                    self.send_header("Location", f"/?v={state['version']}")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    return
                html_bytes = state['html']
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(html_bytes)))
                self.end_headers()
                self.wfile.write(html_bytes)
                return

            if p == "/noto-sans.ttf" and _FONT_BYTES:
                self._send(200, "font/truetype", _FONT_BYTES)
                return
            rel = p.lstrip("/")
            target = (asset_dir / rel).resolve()
            try:
                target.relative_to(asset_dir.resolve())
            except ValueError:
                self._send(403, "text/plain", b"forbidden"); return
            if not target.is_file():
                self._send(404, "text/plain", b"not found"); return
            data = target.read_bytes()
            self._send(200, MIME.get(target.suffix.lower(), "application/octet-stream"), data)

        def _send(self, code, ct, body):
            self.send_response(code)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    return H


_SCALE_CACHE = Path.home() / ".cache" / "vizsh" / "scale.txt"
_SCALE_DEFAULT = 0.6513  # fallback if ffmpeg unavailable


def _measure_libass_scale() -> float:
    """Render a single 'H' with libass/ffmpeg and measure cap height to derive scale."""
    if _SCALE_CACHE.exists():
        try:
            return float(_SCALE_CACHE.read_text().strip())
        except Exception:
            pass

    ass = r"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2

[V4+ Styles]
Format: Alignment, Angle, BackColour, Bold, BorderStyle, Encoding, Fontname, Fontsize, Italic, MarginL, MarginR, MarginV, Name, Outline, OutlineColour, PrimaryColour, ScaleX, ScaleY, SecondaryColour, Shadow, Spacing, StrikeOut, Underline
Style: 0, 0, &H00000000, 0, 0, 0, Noto Sans, 200, 0, 0, 0, 0, T, 0, &H00000000, &H00FFFFFF, 100, 100, &H00000000, 0, 0, 0, 0

[Events]
Format: Effect, End, Layer, MarginL, MarginR, MarginV, Name, Start, Style, Text
Dialogue: , 0:00:30.00, 0, 0, 0, 0, , 0:00:00.00, T, {\an5\pos(960, 540)}H
"""
    import struct
    import tempfile
    BG, FONTSIZE, CAP_RATIO = 0x60, 200, 714 / 1000

    try:
        with tempfile.TemporaryDirectory() as tmp:
            af = Path(tmp) / "t.ass"
            bf = Path(tmp) / "t.bmp"
            af.write_text(ass)
            r = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-f", "lavfi",
                 "-i", f"color=c=0x{BG:02x}{BG:02x}{BG:02x}:s=1920x1080:r=30",
                 "-vf", f"ass={af}",
                 "-ss", "0:00:00.5", "-frames:v", "1", str(bf)],
                capture_output=True, timeout=20,
            )
            if r.returncode != 0 or not bf.exists():
                return _SCALE_DEFAULT
            data = bf.read_bytes()
            if len(data) < 54 or data[:2] != b"BM":
                return _SCALE_DEFAULT
            px_off = struct.unpack_from("<I", data, 10)[0]
            w      = struct.unpack_from("<i", data, 18)[0]
            h_raw  = struct.unpack_from("<i", data, 22)[0]
            h      = abs(h_raw)
            bpp    = struct.unpack_from("<H", data, 28)[0]
            ch     = bpp // 8
            stride = (w * ch + 3) & ~3
            text_rows = []
            for row in range(h):
                real = (h - 1 - row) if h_raw > 0 else row
                base = px_off + real * stride
                for px in range(w):
                    if abs(data[base + px * ch] - BG) > 30:
                        text_rows.append(row)
                        break
            if not text_rows:
                return _SCALE_DEFAULT
            cap_h  = max(text_rows) - min(text_rows) + 1
            scale  = round(cap_h / (FONTSIZE * CAP_RATIO), 4)
    except Exception:
        return _SCALE_DEFAULT

    try:
        _SCALE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _SCALE_CACHE.write_text(str(scale))
    except Exception:
        pass
    return scale


def find_sh() -> Path | None:
    """Auto-detect video pipeline .sh files in the current directory."""
    found = []
    for p in sorted(Path('.').glob('*.sh')):
        try:
            if SCENE_BLOCK_RE.search(p.read_text(encoding='utf-8', errors='ignore')):
                found.append(p.resolve())
        except Exception:
            pass
    if not found:
        return None
    if len(found) == 1:
        return found[0]
    print("Múltiplos arquivos encontrados:")
    for i, p in enumerate(found, 1):
        print(f"  [{i}] {p.name}")
    try:
        n = int(input("Escolha (número): "))
        if 1 <= n <= len(found):
            return found[n - 1]
    except (ValueError, EOFError, KeyboardInterrupt):
        pass
    return found[0]


class _SSEBroadcaster:
    def __init__(self):
        self._qs: list[queue.Queue] = []
        self._lock = threading.Lock()

    def connect(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._qs.append(q)
        return q

    def disconnect(self, q: queue.Queue) -> None:
        with self._lock:
            self._qs = [x for x in self._qs if x is not q]

    def broadcast(self, msg: str) -> None:
        with self._lock:
            for q in self._qs:
                q.put(msg)


class _FileWatcher:
    def __init__(self, path: Path, on_change):
        self._path = path
        self._on_change = on_change
        self._mtime = path.stat().st_mtime
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        import time as _t
        while True:
            _t.sleep(1)
            try:
                mtime = self._path.stat().st_mtime
                if mtime != self._mtime:
                    self._mtime = mtime
                    self._on_change()
            except Exception:
                pass


def serve(sh_path: Path):
    import time as _time
    sh_path = sh_path.resolve()

    state: dict = {}
    broadcaster = _SSEBroadcaster()

    print("medindo escala do libass... ", end="", flush=True)
    libass_scale = _measure_libass_scale()
    print(f"{libass_scale}")

    def rebuild(scenes=None):
        if scenes is None:
            scenes = parse_sh(sh_path)
        state['version'] = int(_time.time())
        state['html'] = build_html(
            scenes, sh_path.name, state['version'], libass_scale
        ).encode('utf-8')

    rebuild(parse_sh(sh_path))

    def on_change():
        try:
            rebuild()
            broadcaster.broadcast('reload')
            print(f"\n  .sh alterado → {len(parse_sh(sh_path))} cenas recarregadas")
        except Exception as e:
            print(f"\n  erro ao recarregar: {e}")

    _FileWatcher(sh_path, on_change)

    httpd = ThreadingHTTPServer(
        ("127.0.0.1", PORT),
        make_handler(state, sh_path.parent, broadcaster),
    )
    base = f"http://localhost:{PORT}"
    url  = f"{base}/?v={state['version']}"
    print(f"vizsh  {base}  (Ctrl+C para sair)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrando.")
        httpd.server_close()


# ─── main ──────────────────────────────────────────────────────────────────────

def main(argv):
    debug = "--debug" in argv[1:]
    args  = [a for a in argv[1:] if not a.startswith("--")]

    if args:
        sh = Path(args[0]).resolve()
    else:
        sh = find_sh()
        if sh is None:
            print("uso: vizsh <arquivo.sh>", file=sys.stderr)
            print("     (ou execute no diretório que contém o .sh)", file=sys.stderr)
            return 2
        print(f"encontrado: {sh.name}")

    if debug:
        print(json.dumps(parse_sh(sh), indent=2, ensure_ascii=False))
        return 0

    serve(sh)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
