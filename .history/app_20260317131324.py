import os
import subprocess
import hashlib
import shutil
import time
import requests
import re

from flask import Flask, jsonify, render_template
from threading import Thread, Lock
from datetime import datetime
from flask_cors import CORS
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)
CORS(app)

stream_lock = Lock()

# ==============================
# CONFIG
# ==============================
BASE_API = "https://i-see.iconpln.co.id/backend"

BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

CLEANUP_INTERVAL = 5
EXPIRE_MINUTES = 2

active_streams = {}

# ==============================
# SESSION (ANTI TIMEOUT)
# ==============================
session = requests.Session()

retry = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504]
)

adapter = HTTPAdapter(max_retries=retry)
session.mount("http://", adapter)
session.mount("https://", adapter)


def safe_get(url):
    return session.get(url, timeout=(5, 10), verify=False)


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
    return url and ".m3u8" in url.lower()


# ==============================
# VALIDASI STREAM
# ==============================
def check_stream_valid(url):
    try:
        r = requests.get(url, timeout=5, verify=False)
        content_type = r.headers.get("Content-Type", "")

        print("Content-Type:", content_type)

        if "application/json" in content_type:
            return False, r.text

        if any(x in content_type for x in ["video", "octet-stream", "mpegurl"]):
            return True, None

        return False, "Content-Type tidak dikenali"

    except Exception as e:
        return False, str(e)


# ==============================
# FFMPEG
# ==============================
def run_ffmpeg_to_hls(source_url, stream_id):
    output_dir = create_hls_folder(stream_id)
    output_file = os.path.join(output_dir, "index.m3u8")

    ffmpeg_path = r"C:\ffmpeg\bin\ffmpeg.exe"

    cmd = [
        ffmpeg_path,
        "-y",
        "-rtsp_transport", "tcp",
        "-i", source_url,
        "-c", "copy",
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "5",
        "-hls_flags", "delete_segments",
        output_file
    ]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        active_streams[stream_id]["proc"] = proc
        proc.wait()
    except Exception as e:
        print("FFMPEG ERROR:", e)


# ==============================
# CLEANUP
# ==============================
def auto_cleanup():
    while True:
        now = datetime.now()

        for stream_id, info in list(active_streams.items()):
            age = (now - info["last_access"]).total_seconds() / 60

            if age > EXPIRE_MINUTES:
                folder = get_stream_folder(stream_id)

                try:
                    proc = info.get("proc")
                    if proc and proc.poll() is None:
                        proc.kill()

                    if os.path.exists(folder):
                        shutil.rmtree(folder)

                    active_streams.pop(stream_id)

                except Exception as e:
                    print("CLEANUP ERROR:", e)

        time.sleep(CLEANUP_INTERVAL)


# ==============================
# ENDPOINT
# ==============================
@app.route("/")
def index():
    return "OK"


@app.route("/ping/<stream_id>")
def ping(stream_id):
    path = os.path.join(BASE_HLS_DIR, stream_id, "index.m3u8")
    return jsonify({"ready": os.path.exists(path)})


@app.route("/livestream/iOS/<token>")
def play_camera(token):
    try:
        api_url = f"{BASE_API}/api/View/EmbedStaticLink?token={token}"
        resp = safe_get(api_url)
        data = resp.json()["data"][0]

        streaming_url = data.get("streamingURL")

        if not streaming_url:
            return render_template("player.html",
                hls_url="",
                stream_id="",
                fallback_url="",
                is_offline=True,
                error_message="Stream tidak tersedia"
            )

        # =========================
        # VALIDASI STREAM
        # =========================
        is_valid, error_msg = check_stream_valid(streaming_url)

        if not is_valid:
            return render_template("player.html",
                hls_url="",
                stream_id="",
                fallback_url=streaming_url,
                is_offline=True,
                error_message=error_msg or "Stream tidak valid"
            )

        # =========================
        # STREAM ID
        # =========================
        camera_id = data.get("cameraId") or token
        stream_id = hashlib.md5(str(camera_id).encode()).hexdigest()[:10]

    except Exception as e:
        return render_template("player.html",
            hls_url="",
            stream_id="",
            fallback_url="",
            is_offline=True,
            error_message=str(e)
        )

    # =========================
    # START FFMPEG
    # =========================
    if not is_hls(streaming_url):
        with stream_lock:
            if stream_id not in active_streams:
                active_streams[stream_id] = {
                    "source": streaming_url,
                    "last_access": datetime.now()
                }

                Thread(
                    target=run_ffmpeg_to_hls,
                    args=(streaming_url, stream_id),
                    daemon=True
                ).start()

    # =========================
    # WAIT HLS READY
    # =========================
    hls_path = os.path.join(BASE_HLS_DIR, stream_id, "index.m3u8")

    for _ in range(10):
        if os.path.exists(hls_path):
            break
        time.sleep(0.5)

    if not os.path.exists(hls_path):
        return render_template("player.html",
            hls_url="",
            stream_id=stream_id,
            fallback_url=streaming_url,
            is_offline=True,
            error_message="FFMPEG gagal / stream tidak jalan"
        )

    hls_url = f"/static/hls/{stream_id}/index.m3u8"

    return render_template("player.html",
        hls_url=hls_url,
        stream_id=stream_id,
        fallback_url=streaming_url,
        is_offline=False,
        error_message=""
    )


# ==============================
# MAIN
# ==============================
if __name__ == "__main__":
    Thread(target=auto_cleanup, daemon=True).start()
    app.run(host="0.0.0.0", port=2881, debug=True)