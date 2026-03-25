import os
import subprocess
import hashlib
import shutil
import time
import requests
import re
from flask import Flask, request, jsonify, render_template_string, redirect, url_for
from threading import Thread
from datetime import datetime
from flask_cors import CORS

try:
    import psutil
except:
    psutil = None

app = Flask(__name__)
CORS(app)

# ==============================
# KONFIG
# ==============================
BASE_API = "https://i-see.iconpln.co.id/backend"

BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

CLEANUP_INTERVAL = 4
EXPIRE_MINUTES = 2

MAX_RETRY_API = 3
MAX_RETRY_FFMPEG = 3
RETRY_DELAY = 2

active_streams = {}
token_to_camera = {}

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

def parse_ffmpeg_error(log_path):
    if not os.path.exists(log_path):
        return "unknown"

    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read().lower()

        if "unauthorized" in content:
            return "auth_failed"
        if "timeout" in content:
            return "timeout"
        if "connection refused" in content:
            return "connection_refused"
        if "404" in content:
            return "not_found"
        if "no route" in content:
            return "network_unreachable"
        if "codec" in content:
            return "invalid_stream"

        return "unknown"
    except:
        return "unknown"

# ==============================
# FFMPEG WITH RETRY
# ==============================

def run_ffmpeg_to_hls(source_url, stream_id):
    output_dir = create_hls_folder(stream_id)
    output_file = os.path.join(output_dir, "index.m3u8")
    log_file = os.path.join(output_dir, "ffmpeg.log")

    ffmpeg_path = r"C:\ffmpeg\bin\ffmpeg.exe"

    for attempt in range(MAX_RETRY_FFMPEG):
        print(f"[FFMPEG RETRY {attempt+1}] {stream_id}")

        cmd = [ffmpeg_path, "-y"]

        if source_url.lower().startswith("rtsp"):
            cmd += ["-rtsp_transport", "tcp", "-stimeout", "5000000"]

        cmd += [
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", source_url,
            "-c", "copy",
            "-f", "hls",
            "-hls_time", "4",
            "-hls_list_size", "5",
            "-hls_flags", "delete_segments",
            output_file
        ]

        try:
            f = open(log_file, "w", encoding="utf-8")
            proc = subprocess.Popen(cmd, stdout=f, stderr=f)

            active_streams[stream_id]["proc"] = proc
            active_streams[stream_id]["log_file"] = f

            time.sleep(5)

            if proc.poll() is None:
                print("[FFMPEG OK]")
                proc.wait()
                return
            else:
                print("[FFMPEG FAIL CEPAT]")

        except Exception as e:
            print(f"[FFMPEG ERROR] {e}")

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

    print("[FFMPEG FAILED TOTAL]")

    error_type = parse_ffmpeg_error(log_file)
    active_streams[stream_id]["failed"] = True
    active_streams[stream_id]["error_type"] = error_type

# ==============================
# ENDPOINT
# ==============================

@app.route("/")
def home():
    return "RUNNING"

@app.route("/livestream/iOS/<token>")
def play_camera(token):

    # ==============================
    # RETRY API
    # ==============================
    streaming_url = None
    camera_id = None

    for attempt in range(MAX_RETRY_API):
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

        except Exception as e:
            print(f"[API RETRY {attempt+1}] {e}")
            time.sleep(RETRY_DELAY)

    if not streaming_url:
        return "<h2>Connection Timeout / Video Offline</h2>", 504

    raw_id = camera_id if camera_id else token
    stream_id = hashlib.md5(str(raw_id).encode()).hexdigest()[:10]
    # ==============================
    # CONVERT
    # ==============================
    if not is_hls(streaming_url):

        if stream_id not in active_streams:
            active_streams[stream_id] = {
                "source": streaming_url,
                "time": datetime.now(),
                "last_access": datetime.now(),
                "viewers": 0
            }

            Thread(target=run_ffmpeg_to_hls, args=(streaming_url, stream_id), daemon=True).start()

        hls_url = f"/static/hls/{stream_id}/index.m3u8"
    else:
        hls_url = streaming_url

    # ==============================
    # HTML
    # ==============================
    return render_template_string(f"""
    <html>
    <head>
        <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    </head>
    <body style="background:black">
        <video id="video" controls autoplay muted style="width:80%"></video>
        <h3 id="msg" style="color:white"></h3>

        <script>
        let video = document.getElementById("video");
        let msg = document.getElementById("msg");
        let src = "{hls_url}";
        let streamId = "{stream_id}";

        async function check() {{
            let res = await fetch("/stream-ready/" + streamId);
            let data = await res.json();

            if (data.failed) {{
                let m = "Video offline";

                switch(data.error){{
                    case "timeout": m="Timeout"; break;
                    case "auth_failed": m="Auth gagal"; break;
                    case "connection_refused": m="Kamera mati"; break;
                }}

                msg.innerText = m;
                return;
            }}

            if (data.ready) {{
                if (Hls.isSupported()) {{
                    let hls = new Hls();
                    hls.loadSource(src);
                    hls.attachMedia(video);
                }} else {{
                    video.src = src;
                }}
            }} else {{
                setTimeout(check,1000);
            }}
        }}

        check();
        </script>
    </body>
    </html>
    """)

@app.route("/stream-ready/<stream_id>")
def ready(stream_id):
    info = active_streams.get(stream_id)

    if info and info.get("failed"):
        return jsonify({"ready": False, "failed": True, "error": info.get("error_type")})

    path = os.path.join(get_stream_folder(stream_id), "index.m3u8")
    return jsonify({"ready": os.path.exists(path)})

# ==============================
# RUN
# ==============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=2881, debug=True)