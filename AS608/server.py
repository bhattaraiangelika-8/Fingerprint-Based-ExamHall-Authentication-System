import base64
import json
import socket
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request

app = Flask(__name__)

IMAGE_SIZE = 36864  # 288x256/2
latest_image = None  # stores raw bytes
latest_time = None
SAVE_DIR = Path("captures")
SAVE_DIR.mkdir(exist_ok=True)


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


@app.route("/")
def index():
    return INDEX_HTML


@app.route("/upload", methods=["POST"])
def upload():
    global latest_image, latest_time
    data = request.get_data()
    if len(data) != IMAGE_SIZE:
        return jsonify({"error": f"Expected {IMAGE_SIZE} bytes, got {len(data)}"}), 400

    latest_image = data
    latest_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    # Save to disk
    filename = f"fingerprint_{latest_time}.raw"
    filepath = SAVE_DIR / filename
    filepath.write_bytes(data)
    print(f"[{latest_time}] Received image ({len(data)} bytes) -> {filepath}")

    return jsonify({"status": "ok", "saved": str(filepath)})


@app.route("/image")
def image():
    global latest_image
    if latest_image is None:
        return jsonify({"error": "No image captured yet"}), 404
    b64 = base64.b64encode(latest_image).decode("ascii")
    return jsonify({"data": b64, "time": latest_time})


@app.route("/status")
def status():
    return jsonify({"ready": latest_image is not None, "time": latest_time})


INDEX_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>AS608 Fingerprint Viewer</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #1a1a2e; color: #eee; display: flex; flex-direction: column; align-items: center; min-height: 100vh; padding: 20px; }
  h1 { margin-bottom: 10px; color: #00d4ff; }
  .info { color: #888; margin-bottom: 20px; font-size: 14px; }
  #status { padding: 10px 20px; margin-bottom: 20px; border-radius: 6px; font-size: 14px; background: #16213e; border: 1px solid #0f3460; min-width: 300px; text-align: center; }
  .canvas-wrap { position: relative; border: 2px solid #0f3460; border-radius: 8px; overflow: hidden; }
  canvas { display: block; image-rendering: pixelated; }
  .controls { margin-top: 20px; display: flex; gap: 10px; align-items: center; }
  button { padding: 10px 24px; border: none; border-radius: 6px; font-size: 14px; cursor: pointer; background: #0f3460; color: #eee; transition: background 0.2s; }
  button:hover { background: #00d4ff; color: #000; }
  button:disabled { opacity: 0.4; cursor: not-allowed; }
  .label { font-size: 13px; color: #888; }
  .scale-btn { background: #16213e; }
  .scale-btn.active { background: #00d4ff; color: #000; }
</style>
</head>
<body>
  <h1>AS608 Fingerprint Viewer</h1>
  <div class="info">Waiting for ESP32 to send images...</div>
  <div id="status">Polling for image...</div>
  <div class="canvas-wrap">
    <canvas id="fp" width="256" height="288"></canvas>
  </div>
  <div class="controls">
    <button onclick="fetchImage()">Fetch Latest</button>
    <button id="autoBtn" onclick="toggleAuto()">Auto Poll: ON</button>
    <span class="label">Scale:</span>
    <button class="scale-btn active" onclick="setScale(1,this)">1x</button>
    <button class="scale-btn" onclick="setScale(2,this)">2x</button>
    <button class="scale-btn" onclick="setScale(3,this)">3x</button>
  </div>

<script>
const canvas = document.getElementById('fp');
const ctx = canvas.getContext('2d');
const statusEl = document.getElementById('status');
const autoBtn = document.getElementById('autoBtn');
let autoPoll = true;
let pollTimer = null;
let lastTime = null;

function decodeAndDraw(b64data) {
    const raw = atob(b64data);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);

    const width = 256, height = 288;
    const imageData = ctx.createImageData(width, height);
    let idx = 0;
    for (let i = 0; i < bytes.length; i++) {
        const hi = bytes[i] & 0xF0;
        const lo = (bytes[i] & 0x0F) << 4;
        imageData.data[idx * 4]     = hi;
        imageData.data[idx * 4 + 1] = hi;
        imageData.data[idx * 4 + 2] = hi;
        imageData.data[idx * 4 + 3] = 255;
        idx++;
        imageData.data[idx * 4]     = lo;
        imageData.data[idx * 4 + 1] = lo;
        imageData.data[idx * 4 + 2] = lo;
        imageData.data[idx * 4 + 3] = 255;
        idx++;
    }
    ctx.putImageData(imageData, 0, 0);
}

async function fetchImage() {
    statusEl.textContent = 'Fetching...';
    statusEl.style.borderColor = '#0f3460';
    try {
        const res = await fetch('/image');
        const json = await res.json();
        if (json.error) {
            statusEl.textContent = 'No image yet';
            return;
        }
        if (json.time !== lastTime) {
            decodeAndDraw(json.data);
            lastTime = json.time;
            statusEl.textContent = 'Image loaded: ' + json.time;
            statusEl.style.borderColor = '#00d4ff';
        } else {
            statusEl.textContent = 'No new image. Last: ' + json.time;
        }
    } catch (e) {
        statusEl.textContent = 'Error: ' + e.message;
        statusEl.style.borderColor = '#ff4444';
    }
}

function toggleAuto() {
    autoPoll = !autoPoll;
    autoBtn.textContent = 'Auto Poll: ' + (autoPoll ? 'ON' : 'OFF');
    if (autoPoll) startPoll(); else stopPoll();
}

function startPoll() {
    pollTimer = setInterval(fetchImage, 1500);
}

function stopPoll() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
}

function setScale(s, btn) {
    canvas.style.width = (256 * s) + 'px';
    canvas.style.height = (288 * s) + 'px';
    document.querySelectorAll('.scale-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}

startPoll();
</script>
</body>
</html>"""


if __name__ == "__main__":
    ip = get_local_ip()
    print(f"\n{'='*50}")
    print(f"  AS608 Fingerprint Server")
    print(f"  Listening on: http://{ip}:5000")
    print(f"  Set SERVER_IP in ESP32 sketch to: {ip}")
    print(f"  Captures saved to: {SAVE_DIR.resolve()}")
    print(f"{'='*50}\n")
    app.run(host="0.0.0.0", port=5000)
