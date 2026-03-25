import os
import subprocess
import hashlib
import time
import requests
import shutil
from flask import Flask, jsonify, render_template_string
from threading import Thread
from datetime import datetime
from flask_cors import CORS
import traceback

app = Flask(__name__)
CORS(app)

# ==============================
# KONFIG
# ==============================
BASE_API = "https://i-see.iconpln.co.id/backend"

BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

MAX_RETRY_API = 3
MAX_RETRY_FFMPEG = 3
RETRY_DELAY = 2

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

def is_hls(url):
    return ".m3u8" in url.lower()

# ==============================
# STREAM HEALTH CHECK
# ==============================

def is_stream_stale(stream_id, max_delay=10):
    folder = get_stream_folder(stream_id)

    if not os.path.exists(folder):
        return True

    ts_files = [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.endswith(".ts")
    ]

    if not ts_files:
        return True

    latest_file = max(ts_files, key=os.path.getmtime)
    delay = time.time() - os.path.getmtime(latest_file)

    return delay > max_delay


def reset_stream(stream_id):
    info = active_streams.get(stream_id)

    # kill ffmpeg
    if info:
        proc = info.get("proc")
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except:
                pass

    # hapus folder
    folder = get_stream_folder(stream_id)
    if os.path.exists(folder):
        try:
            shutil.rmtree(folder)
        except:
            pass

    active_streams.pop(stream_id, None)

# ==============================
# FFMPEG
# ==============================

def run_ffmpeg_to_hls(source_url, stream_id):
    output_dir = create_hls_folder(stream_id)
    output_file = os.path.join(output_dir, "index.m3u8")
    log_file = os.path.join(output_dir, "ffmpeg.log")

    ffmpeg_path = r"C:\ffmpeg\bin\ffmpeg.exe"

    for _ in range(MAX_RETRY_FFMPEG):

        cmd = [ffmpeg_path, "-y"]

        if source_url.lower().startswith("rtsp"):
            cmd += ["-rtsp_transport", "tcp", "-stimeout", "5000000"]

        cmd += [
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", source_url,
            "-c", "copy",
            "-f", "hls",
            "-hls_time", "2",
            "-hls_list_size", "3",
            "-hls_segment_filename", os.path.join(output_dir, "seg_%03d.ts"),
            "-hls_flags", "delete_segments+append_list+omit_endlist+temp_file",
            output_file
        ]

        try:
            f = open(log_file, "w", encoding="utf-8")
            proc = subprocess.Popen(cmd, stdout=f, stderr=f)

            if stream_id in active_streams:
                active_streams[stream_id]["proc"] = proc
                active_streams[stream_id]["log_file"] = f

            time.sleep(5)

            # kalau masih hidup → biarkan jalan
            if proc.poll() is None:
                return

        except Exception as e:
            print("FFMPEG ERROR:", e)

        finally:
            try:
                f.close()
            except:
                pass

            try:
                proc.kill()
            except:
                pass

        time.sleep(RETRY_DELAY)

    if stream_id in active_streams:
        active_streams[stream_id]["failed"] = True

# ==============================
# WATCHDOG (AUTO RESET)
# ==============================

def watchdog():
    while True:
        for stream_id in list(active_streams.keys()):
            if is_stream_stale(stream_id, 15):
                print(f"[WATCHDOG] reset {stream_id}")
                reset_stream(stream_id)
        time.sleep(5)

Thread(target=watchdog, daemon=True).start()

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
            api_url = f"{BASE_API}/api/View/EmbedStaticLink?token={token}"
            resp = requests.get(api_url, timeout=10, verify=False)
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

    if not is_hls(streaming_url):

        # cegah double ffmpeg
        if stream_id in active_streams:
            proc = active_streams[stream_id].get("proc")
            if proc and proc.poll() is None:
                return jsonify({
                    "ok": True,
                    "stream_id": stream_id,
                    "hls_url": f"/static/hls/{stream_id}/index.m3u8"
                })

        active_streams[stream_id] = {
            "source": streaming_url,
            "time": datetime.now()
        }

        Thread(
            target=run_ffmpeg_to_hls,
            args=(streaming_url, stream_id),
            daemon=True
        ).start()

        hls_url = f"/static/hls/{stream_id}/index.m3u8"

    else:
        hls_url = streaming_url

    return jsonify({
        "ok": True,
        "stream_id": stream_id,
        "hls_url": hls_url
    })

@app.route("/stream-ready/<stream_id>")
def ready(stream_id):
    info = active_streams.get(stream_id)

    if info and info.get("failed"):
        return jsonify({
            "ready": False,
            "failed": True
        })

    # 🔥 AUTO RESET kalau delay
    if is_stream_stale(stream_id):
        reset_stream(stream_id)
        return jsonify({
            "ready": False,
            "reset": True
        })

    path = os.path.join(get_stream_folder(stream_id), "index.m3u8")

    return jsonify({
        "ready": os.path.exists(path)
    })

# ==============================
# PLAYER PAGE
# ==============================

@app.route("/livestream/iOS/<token>")
def play_camera(token):

    return render_template_string(f"""
    <html>
    <head>
        <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    </head>
    <body style="margin:0;background:black;display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;">

        <div id="loading">Loading...</div>
        <video id="video" controls autoplay muted style="max-width:90%;display:none;"></video>
        <h3 id="msg" style="color:white;"></h3>

        <script>
        let token = "{token}";
        let video = document.getElementById("video");
        let msg = document.getElementById("msg");
        let loading = document.getElementById("loading");

        function showVideo() {{
            loading.style.display = "none";
            video.style.display = "block";
        }}

        function showError(t) {{
            loading.style.display = "none";
            msg.innerText = t;
        }}

        async function start() {{
            try {{
                let res = await fetch("/start-stream/" + token);
                let data = await res.json();

                if (!data.ok) {{
                    showError("Gagal ambil stream");
                    return;
                }}

                let streamId = data.stream_id;
                let src = data.hls_url;

                async function check() {{
                    let r = await fetch("/stream-ready/" + streamId);
                    let d = await r.json();

                    if (d.failed) {{
                        showError("Stream error");
                        return;
                    }}

                    if (d.reset) {{
                        console.log("RESET STREAM");
                        start();
                        return;
                    }}

                    if (d.ready) {{
                        showVideo();

                        if (Hls.isSupported()) {{
                            let hls = new Hls();
                            hls.loadSource(src + "?t=" + Date.now());
                            hls.attachMedia(video);
                        }} else {{
                            video.src = src;
                        }}

                    }} else {{
                        setTimeout(check, 1000);
                    }}
                }}

                check();

            }} catch(e) {{
                showError("Error koneksi");
            }}
        }}

        start();
        </script>

    </body>
    </html>
    """)

# ==============================
# RUN
# ==============================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=2881, debug=True)