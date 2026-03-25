import os
import re
import time
import uuid
import shutil
import subprocess
import requests

from flask import Flask, jsonify, request, send_from_directory
from threading import Thread

app = Flask(__name__)

BASE_API = "https://i-see.iconpln.co.id"

HLS_ROOT = "static/hls"

active_streams = {}
token_to_camera = {}

os.makedirs(HLS_ROOT, exist_ok=True)


# ===============================
# API RETRY
# ===============================

def request_with_retry(url, retries=3, timeout=10):

    for attempt in range(retries):

        try:

            resp = requests.get(url, timeout=timeout, verify=False)
            resp.raise_for_status()

            return resp

        except requests.exceptions.Timeout:

            print(f"[API] timeout {attempt+1}/{retries}")

        except requests.exceptions.RequestException as e:

            print(f"[API] error {attempt+1}/{retries} -> {e}")

        time.sleep(2 ** attempt)

    print("[API] kamera offline")
    return None


# ===============================
# TOKEN GENERATOR
# ===============================

def generate_token(camera_id):

    api_url = f"{BASE_API}/api/View/GenerateCameraLink?cameraId={camera_id}"

    resp = request_with_retry(api_url)

    if not resp:
        raise Exception("kamera offline")

    data = resp.json()

    raw_streaming_url = data.get("streamingURL")

    if not raw_streaming_url:
        raise Exception("streamingURL tidak ditemukan")

    match = re.search(r"token=([^&]+)", raw_streaming_url)

    if not match:
        raise Exception("token tidak ditemukan")

    return match.group(1)


# ===============================
# HLS FOLDER
# ===============================

def create_hls_folder(stream_id):

    folder = os.path.join(HLS_ROOT, stream_id)

    os.makedirs(folder, exist_ok=True)

    return folder


# ===============================
# FFMPEG STREAM
# ===============================

def run_ffmpeg_to_hls(source_url, stream_id):

    output_dir = create_hls_folder(stream_id)

    output_file = os.path.join(output_dir, "index.m3u8")

    log_file = os.path.join(output_dir, "ffmpeg.log")

    ffmpeg = r"C:\ffmpeg\bin\ffmpeg.exe"

    cmd = [
        ffmpeg,
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

        log = open(log_file, "w", encoding="utf-8")

        proc = subprocess.Popen(cmd, stdout=log, stderr=log)

        if stream_id in active_streams:

            active_streams[stream_id]["proc"] = proc
            active_streams[stream_id]["source"] = source_url
            active_streams[stream_id]["log"] = log

        proc.wait()

    except Exception as e:

        print("[FFMPEG ERROR]", e)

    finally:

        try:
            log.close()
        except:
            pass

        if stream_id in active_streams:
            active_streams[stream_id].pop("proc", None)


# ===============================
# PLAY CAMERA
# ===============================

@app.route("/play/<camera_id>")
def play_camera(camera_id):

    try:

        token = generate_token(camera_id)

    except:

        return """
        <html>
        <body style="background:black;color:white;display:flex;align-items:center;justify-content:center;height:100vh;">
        <div>
        <h2>Kamera Offline</h2>
        </div>
        </body>
        </html>
        """

    api_url = f"{BASE_API}/api/View/CameraLink?token={token}"

    resp = request_with_retry(api_url)

    if not resp:

        return "<h1>Kamera offline</h1>"

    data = resp.json()

    streaming_url = data.get("streamingURL")

    stream_id = uuid.uuid4().hex[:10]

    active_streams[stream_id] = {
        "viewers": 1
    }

    thread = Thread(
        target=run_ffmpeg_to_hls,
        args=(streaming_url, stream_id),
        daemon=True
    )

    thread.start()

    return f"""
<html>
<head>
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
</head>
<body>

<video id="video" controls autoplay width="800"></video>

<script>

var video = document.getElementById("video")

var hls = new Hls()

hls.loadSource("/static/hls/{stream_id}/index.m3u8")

hls.attachMedia(video)

</script>

</body>
</html>
"""


# ===============================
# RENEW STREAM
# ===============================

@app.route("/renew_stream/<token>")
def renew_stream(token):

    camera_id = token_to_camera.get(token)

    if not camera_id:

        return jsonify({"error": "invalid token"}), 400

    new_token = generate_token(camera_id)

    api_url = f"{BASE_API}/api/View/CameraLink?token={new_token}"

    resp = request_with_retry(api_url)

    if not resp:

        return jsonify({
            "error": "kamera offline"
        }), 500

    data = resp.json()

    return jsonify({
        "streamingUrl": data.get("streamingURL")
    })


# ===============================
# WATCHDOG
# ===============================

def ffmpeg_watchdog():

    while True:

        for stream_id, info in list(active_streams.items()):

            proc = info.get("proc")

            source = info.get("source")

            if not proc:
                continue

            if proc.poll() is not None:

                print("[WATCHDOG] restart", stream_id)

                thread = Thread(
                    target=run_ffmpeg_to_hls,
                    args=(source, stream_id),
                    daemon=True
                )

                thread.start()

        time.sleep(10)


# ===============================
# CLEANUP
# ===============================

def auto_cleanup_hls():

    while True:

        for folder in os.listdir(HLS_ROOT):

            path = os.path.join(HLS_ROOT, folder)

            if folder not in active_streams:

                try:
                    shutil.rmtree(path)
                    print("[CLEANUP]", folder)

                except:
                    pass

        time.sleep(60)


# ===============================
# STATIC HLS
# ===============================

@app.route("/static/hls/<path:path>")
def serve_hls(path):

    return send_from_directory(HLS_ROOT, path)


# ===============================
# MAIN
# ===============================

if __name__ == "__main__":

    Thread(target=auto_cleanup_hls, daemon=True).start()

    Thread(target=ffmpeg_watchdog, daemon=True).start()

    app.run(
        host="0.0.0.0",
        port=2881,
        debug=True
    )