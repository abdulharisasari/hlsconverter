import os
import subprocess
import hashlib
import time
import requests
import shutil
import traceback
import urllib3
from flask import Flask, jsonify, render_template_string
from threading import Thread
from datetime import datetime
from flask_cors import CORS

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
CORS(app)

BASE_API = "https://i-see.iconpln.co.id/backend"

BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

MAX_RETRY_API = 3
MAX_RETRY_FFMPEG = 3
RETRY_DELAY = 2
MAX_FFMPEG = 5

active_streams = {}

# ==============================
# UTIL
# ==============================

def get_stream_folder(stream_id):
    return os.path.join(BASE_HLS_DIR, stream_id)

def create_hls_folder(stream_id):
    folder = get_stream_folder(stream_id)
    os.makedirs(folder, exist_ok=True)
    return folder

def count_active_ffmpeg():
    return sum(
        1 for s in active_streams.values()
        if s.get("proc") and s["proc"].poll() is None
    )

# ==============================
# RESET
# ==============================

def reset_stream(stream_id):
    info = active_streams.get(stream_id)

    if info:
        proc = info.get("proc")
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except:
                pass

    folder = get_stream_folder(stream_id)
    if os.path.exists(folder):
        shutil.rmtree(folder, ignore_errors=True)

    active_streams.pop(stream_id, None)
    print("[RESET]", stream_id)

# ==============================
# FFMPEG
# ==============================

def run_ffmpeg_to_hls(source_url, stream_id):
    output_dir = create_hls_folder(stream_id)
    output_file = os.path.join(output_dir, "index.m3u8")

    ffmpeg_path = r"C:\ffmpeg\bin\ffmpeg.exe"

    for _ in range(MAX_RETRY_FFMPEG):

        cmd = [ffmpeg_path, "-y"]

        if source_url.lower().startswith("rtsp"):
            cmd += [
                "-rtsp_transport", "tcp",
                "-fflags", "nobuffer",
                "-flags", "low_delay"
            ]

        cmd += [
            "-i", source_url,
            "-c", "copy",
            "-f", "hls",
            "-hls_time", "2",
            "-hls_list_size", "3",
            "-hls_segment_filename", os.path.join(output_dir, "seg_%03d.ts"),
            "-hls_flags", "delete_segments+append_list+omit_endlist",
            output_file
        ]

        try:
            print("[FFMPEG START]", stream_id)

            proc = subprocess.Popen(cmd)

            if stream_id in active_streams:
                active_streams[stream_id]["proc"] = proc

            # tunggu sampai m3u8 muncul
            for _ in range(15):
                if os.path.exists(output_file):
                    print("[FFMPEG READY]", stream_id)
                    return
                time.sleep(1)

        except:
            traceback.print_exc()

        try:
            proc.kill()
        except:
            pass

        time.sleep(RETRY_DELAY)

    if stream_id in active_streams:
        active_streams[stream_id]["failed"] = True


# ==============================
# CLEANER (FIX PALING PENTING)
# ==============================

def clean_idle_streams(max_idle=30):
    while True:
        now = time.time()

        for stream_id, info in list(active_streams.items()):
            last = info.get("last_access", now)
            viewers = info.get("viewers", 0)

            # 🔥 fallback (gak ada activity sama sekali)
            if now - last > max_idle:
                print("[FORCE CLEAN]", stream_id)
                reset_stream(stream_id)
                continue

            # 🔥 viewer sudah 0
            if viewers <= 0 and now - last > 10:
                print("[IDLE CLEAN]", stream_id)
                reset_stream(stream_id)

        time.sleep(5)

Thread(target=clean_idle_streams, daemon=True).start()

# ==============================
# ENDPOINT
# ==============================

@app.route("/")
def home():
    return "RUNNING"

@app.route("/start-stream/<token>")
def start_stream(token):

    streaming_url = None
    camera_id = None

    for _ in range(MAX_RETRY_API):
        try:
            resp = requests.get(
                f"{BASE_API}/api/View/EmbedStaticLink?token={token}",
                timeout=10,
                verify=False
            )
            resp.raise_for_status()

            data = resp.json()["data"][0]
            streaming_url = data.get("streamingURL")

            for k in ("cameraId", "cameraID", "camera_id", "CameraId"):
                if k in data:
                    camera_id = data[k]
                    break

            if streaming_url:
                break

        except:
            time.sleep(RETRY_DELAY)

    if not streaming_url:
        return jsonify({"ok": False})

    raw_id = camera_id if camera_id else token
    stream_id = hashlib.md5(str(raw_id).encode()).hexdigest()[:10]

    # 🔥 reuse stream
    if stream_id in active_streams:
        info = active_streams[stream_id]
        info["last_access"] = time.time()
        info["viewers"] = info.get("viewers", 0) + 1

        proc = info.get("proc")
        if proc and proc.poll() is None:
            return jsonify({
                "ok": True,
                "stream_id": stream_id,
                "hls_url": f"/static/hls/{stream_id}/index.m3u8"
            })

    # 🔥 limit ffmpeg
    if count_active_ffmpeg() >= MAX_FFMPEG:
        return jsonify({"ok": False, "error": "Server penuh"})

    active_streams[stream_id] = {
        "source": streaming_url,
        "time": datetime.now(),
        "last_access": time.time(),
        "viewers": 1,
        "failed": False
    }

    Thread(target=run_ffmpeg_to_hls, args=(streaming_url, stream_id), daemon=True).start()

    return jsonify({
        "ok": True,
        "stream_id": stream_id,
        "hls_url": f"/static/hls/{stream_id}/index.m3u8"
    })


@app.route("/stream-ready/<stream_id>")
def ready(stream_id):

    info = active_streams.get(stream_id)
    if info:
        info["last_access"] = time.time()

    path = os.path.join(get_stream_folder(stream_id), "index.m3u8")

    return jsonify({
        "ready": os.path.exists(path)
    })


@app.route("/leave-stream/<stream_id>", methods=["POST", "GET"])
def leave(stream_id):
    info = active_streams.get(stream_id)
    if info:
        info["viewers"] = max(0, info.get("viewers", 1) - 1)
        info["last_access"] = time.time()
        print("[LEAVE]", stream_id, "viewers:", info["viewers"])
    return "ok"


# ==============================
# PLAYER
# ==============================

@app.route("/livestream/iOS/<token>")
def play(token):

    return render_template_string("""
    <html>
    <head>
        <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    </head>
    <body style="margin:0;background:black;display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;">

        <div id="loading" style="color:white;font-size:18px;">Loading stream...</div>
        <video id="video" controls autoplay muted style="max-width:90%;display:none;"></video>

        <script>
        let token = "{{ token }}";
        let streamIdGlobal = null;

        let video = document.getElementById("video");
        let loading = document.getElementById("loading");

        window.addEventListener("beforeunload", function () {
            if (streamIdGlobal) {
                navigator.sendBeacon("/leave-stream/" + streamIdGlobal);
            }
        });

        function showVideo() {
            loading.style.display = "none";
            video.style.display = "block";
        }

        async function start() {

            let res = await fetch("/start-stream/" + token);
            let data = await res.json();

            if (!data.ok) {
                loading.innerText = "❌ " + (data.error || "Gagal stream");
                return;
            }

            let streamId = data.stream_id;
            streamIdGlobal = streamId;

            let src = data.hls_url;

            async function check() {

                let r = await fetch("/stream-ready/" + streamId);
                let d = await r.json();

                if (d.ready) {

                    loading.innerText = "Playing video...";
                    showVideo();

                    if (Hls.isSupported()) {
                        let hls = new Hls();
                        hls.loadSource(src + "?t=" + Date.now());
                        hls.attachMedia(video);
                    } else {
                        video.src = src;
                    }

                } else {
                    loading.innerText = "Downloading segment...";
                    setTimeout(check, 1000);
                }
            }

            check();
        }

        start();
        </script>

    </body>
    </html>
    """, token=token)


# ==============================
# RUN
# ==============================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=2881, debug=True)