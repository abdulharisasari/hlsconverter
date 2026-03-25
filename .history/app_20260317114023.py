import os
import subprocess
import hashlib
import shutil
import time
import requests
import re

from flask import Flask, request, jsonify, render_template, redirect, url_for
from threading import Thread, Lock
from datetime import datetime
from flask_cors import CORS
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)
CORS(app)

stream_lock = Lock()

# ==============================
# KONFIG
# ==============================
BASE_API = "https://i-see.iconpln.co.id/backend"

BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

CLEANUP_INTERVAL = 4
EXPIRE_MINUTES = 2

active_streams = {}
token_to_camera = {}

# ==============================
# REQUEST SESSION
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


# ==============================
# UTIL
# ==============================
def safe_get(url, retries=3):
    for i in range(retries):
        try:
            return session.get(url, timeout=(5, 10), verify=False)
        except requests.exceptions.ConnectTimeout:
            print(f"[RETRY] ConnectTimeout {i+1}/{retries}")
            time.sleep(1)

    raise Exception("API tidak bisa dihubungi")


def get_stream_folder(stream_id):
    return os.path.join(BASE_HLS_DIR, stream_id)


def create_hls_folder(stream_id):
    folder = get_stream_folder(stream_id)
    os.makedirs(folder, exist_ok=True)
    return folder


def is_hls(url):
    return url and url.lower().endswith(".m3u8")


# ==============================
# FFMPEG
# ==============================
def run_ffmpeg_to_hls(source_url, stream_id):
    output_dir = create_hls_folder(stream_id)
    output_file = os.path.join(output_dir, "index.m3u8")

    cmd = [
        "ffmpeg",
        "-y",
        "-rw_timeout", "10000000",
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

    proc = subprocess.Popen(cmd)

    if stream_id in active_streams:
        active_streams[stream_id]["proc"] = proc

    try:
        proc.wait()
    finally:
        if stream_id in active_streams:
            active_streams[stream_id].pop("proc", None)


# ==============================
# CLEANUP
# ==============================
def remove_old_streams():
    now = datetime.now()

    for stream_id, info in list(active_streams.items()):
        last = info.get("last_access", info["time"])
        age = (now - last).total_seconds() / 60

        if age > EXPIRE_MINUTES and info.get("viewers", 0) == 0:
            folder = get_stream_folder(stream_id)

            try:
                proc = info.get("proc")
                if proc and proc.poll() is None:
                    proc.kill()

                if os.path.exists(folder):
                    shutil.rmtree(folder, ignore_errors=True)

                active_streams.pop(stream_id, None)
                print(f"[CLEANUP] {stream_id}")

            except Exception as e:
                print(f"[CLEANUP ERROR] {e}")


def auto_cleanup():
    while True:
        remove_old_streams()
        time.sleep(CLEANUP_INTERVAL)


# ==============================
# API
# ==============================
def generate_token(camera_id):
    url = f"{BASE_API}/api/View/GenerateCameraLink?cameraId={camera_id}"
    resp = safe_get(url)
    resp.raise_for_status()

    data = resp.json()
    raw = data.get("streamingURL")

    match = re.search(r"token=([^&]+)", raw)
    return match.group(1)


@app.route("/")
def home():
    return "OK"


@app.route("/generateLinkIOS")
def generate_link():
    camera_id = request.args.get("cameraId")

    token = generate_token(camera_id)
    token_to_camera[token] = camera_id

    return jsonify({
        "url": f"/livestream/iOS/{token}"
    })


# ==============================
# PLAYER
# ==============================
@app.route("/livestream/iOS/<token>")
def play_camera(token):

    try:
        api_url = f"{BASE_API}/api/View/EmbedStaticLink?token={token}"
        resp = safe_get(api_url)
        resp.raise_for_status()

        data = (resp.json().get("data") or [{}])[0]
        streaming_url = data.get("streamingURL")

        if not streaming_url:
            return "stream tidak ada", 500

    except Exception as e:
        return str(e), 500

    stream_id = hashlib.md5(token.encode()).hexdigest()[:10]

    # =========================
    # HLS langsung
    # =========================
    if is_hls(streaming_url):
        hls_url = streaming_url

    # =========================
    # Convert
    # =========================
    else:
        with stream_lock:
            if (
                stream_id not in active_streams
                or active_streams[stream_id].get("proc") is None
            ):
                active_streams[stream_id] = {
                    "time": datetime.now(),
                    "viewers": 0,
                    "last_access": datetime.now()
                }

                Thread(
                    target=run_ffmpeg_to_hls,
                    args=(streaming_url, stream_id),
                    daemon=True
                ).start()

        hls_url = f"/static/hls/{stream_id}/index.m3u8"

    return render_template(
        "player.html",
        hls_url=hls_url,
        stream_id=stream_id,
        token=token
    )


# ==============================
# STREAM CONTROL
# ==============================
@app.route("/ping/<stream_id>")
def ping(stream_id):
    if stream_id in active_streams:
        active_streams[stream_id]["last_access"] = datetime.now()
    return "", 204


@app.route("/open/<stream_id>", methods=["POST"])
def open_stream(stream_id):
    if stream_id in active_streams:
        active_streams[stream_id]["viewers"] += 1
    return "", 204


@app.route("/close/<stream_id>", methods=["POST"])
def close_stream(stream_id):
    if stream_id in active_streams:
        active_streams[stream_id]["viewers"] -= 1
    return "", 204


@app.route("/stream-ready/<stream_id>")
def ready(stream_id):
    file = os.path.join(get_stream_folder(stream_id), "index.m3u8")
    return jsonify({"ready": os.path.exists(file)})


# ==============================
# MAIN
# ==============================
if __name__ == "__main__":
    Thread(target=auto_cleanup, daemon=True).start()
    app.run(host="0.0.0.0", port=2881, debug=True)