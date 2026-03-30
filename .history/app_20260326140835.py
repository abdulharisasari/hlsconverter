import os
import subprocess
import hashlib
import shutil
import time
import requests
from flask import Flask, jsonify, render_template_string
from threading import Thread
from datetime import datetime, timedelta
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BASE_API = "https://i-see.iconpln.co.id/backend"

BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

CLEANUP_INTERVAL = 5
EXPIRE_MINUTES = 2

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

# ==============================
# FFMPEG
# ==============================

def run_ffmpeg_to_hls(source_url, stream_id):
    output_dir = create_hls_folder(stream_id)
    output_file = os.path.join(output_dir, "index.m3u8")

    ffmpeg_path = r"C:\ffmpeg\bin\ffmpeg.exe"

    cmd = [ffmpeg_path, "-y"]

    if source_url.lower().startswith("rtsp"):
        cmd += [
            "-rtsp_transport", "tcp",
            "-fflags", "nobuffer",
            "-flags", "low_delay"
        ]

    cmd += [
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-i", source_url,
        "-c", "copy",
        "-f", "hls",
        "-hls_time", "2",
        "-hls_list_size", "10",
        "-hls_flags", "append_list+omit_endlist",
        os.path.join(output_dir, "index.m3u8")
    ]

    try:
        print("[FFMPEG START]", stream_id)

        proc = subprocess.Popen(cmd)

        if stream_id in active_streams:
            active_streams[stream_id]["proc"] = proc

        proc.wait()

    except Exception as e:
        print("[FFMPEG ERROR]", e)

    finally:
        if stream_id in active_streams:
            active_streams[stream_id].pop("proc", None)

# ==============================
# CLEANUP + AUTO RECOVERY
# ==============================

def remove_old_streams():
    now = datetime.now()

    for stream_id, info in list(active_streams.items()):
        last = info.get("last_access", now)
        viewers = info.get("viewers", 0)
        folder = get_stream_folder(stream_id)

        age = (now - last).total_seconds()

        proc = info.get("proc")
        is_dead = (not proc) or (proc.poll() is not None)

        # cek file HLS
        index_file = os.path.join(folder, "index.m3u8")
        is_stale = True

        if os.path.exists(index_file):
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(index_file))
                if (now - mtime).total_seconds() < 15:
                    is_stale = False
            except:
                pass

        # =========================
        # 🔥 MASIH ADA VIEWER
        # =========================
        if viewers > 0:

            # fallback kalau viewer nyangkut
            if age > 60:
                print("[FORCE RESET VIEWER]", stream_id)
                info["viewers"] = 0
                continue

            if is_dead or is_stale:
                print("[RECOVER STREAM]", stream_id)

                try:
                    Thread(
                        target=run_ffmpeg_to_hls,
                        args=(info["source"], stream_id),
                        daemon=True
                    ).start()

                    info["last_access"] = datetime.now()

                except Exception as e:
                    print("[RECOVER ERROR]", e)

            continue

        # =========================
        # 🔥 TIDAK ADA VIEWER
        # =========================
        if viewers <= 0 and age > EXPIRE_MINUTES * 60:

            print("[CLEANUP]", stream_id)

            try:
                if proc and proc.poll() is None:
                    proc.kill()
            except:
                pass

            try:
                if os.path.exists(folder):
                    shutil.rmtree(folder, ignore_errors=True)
            except:
                pass

            active_streams.pop(stream_id, None)

def auto_cleanup():
    while True:
        remove_old_streams()
        time.sleep(CLEANUP_INTERVAL)

# ==============================
# API
# ==============================

@app.route("/start-stream/<token>")
def start_stream(token):

    try:
        resp = requests.get(
            f"{BASE_API}/api/View/EmbedStaticLink?token={token}",
            timeout=10,
            verify=False
        )
        data = resp.json()["data"][0]
        streaming_url = data.get("streamingURL")

    except:
        return jsonify({"ok": False})

    stream_id = hashlib.md5(token.encode()).hexdigest()[:10]

    if stream_id not in active_streams:
        active_streams[stream_id] = {
            "source": streaming_url,
            "viewers": 0,
            "last_access": datetime.now()
        }

        Thread(
            target=run_ffmpeg_to_hls,
            args=(streaming_url, stream_id),
            daemon=True
        ).start()

    return jsonify({
        "ok": True,
        "stream_id": stream_id,
        "hls_url": f"/static/hls/{stream_id}/index.m3u8"
    })

@app.route("/ping/<stream_id>")
def ping(stream_id):
    if stream_id in active_streams:
        active_streams[stream_id]["last_access"] = datetime.now()
    return "", 204

@app.route("/open/<stream_id>", methods=["POST"])
def open_stream(stream_id):
    if stream_id in active_streams:
        active_streams[stream_id]["viewers"] += 1
        active_streams[stream_id]["last_access"] = datetime.now()
    return "", 204

@app.route("/close/<stream_id>", methods=["POST"])
def close_stream(stream_id):
    if stream_id in active_streams:
        info = active_streams[stream_id]
        info["viewers"] = max(0, info["viewers"] - 1)

        if info["viewers"] == 0:
            info["last_access"] = datetime.now() - timedelta(minutes=EXPIRE_MINUTES+1)

    return "", 204

@app.route("/stream-ready/<stream_id>")
def ready(stream_id):
    path = os.path.join(get_stream_folder(stream_id), "index.m3u8")
    return jsonify({"ready": os.path.exists(path)})

# ==============================
# PLAYER
# ==============================

@app.route("/livestream/<token>")
def player(token):
    return render_template_string("""
    <html>
    <head>
        <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    </head>
    <body style="background:black;display:flex;justify-content:center;align-items:center;height:100vh">

    <video id="video" controls autoplay muted style="width:80%"></video>

    <script>
    let token = "{{token}}"
    let streamId = null
    let video = document.getElementById("video")

    async function start(){
        let res = await fetch("/start-stream/" + token)
        let data = await res.json()

        streamId = data.stream_id

        fetch("/open/" + streamId, {method:"POST"})

        setInterval(()=>{
            fetch("/ping/" + streamId)
        },5000)

        if(Hls.isSupported()){
            let hls = new Hls()
            hls.loadSource(data.hls_url)
            hls.attachMedia(video)
        }else{
            video.src = data.hls_url
        }
    }

    window.addEventListener("beforeunload", ()=>{
        navigator.sendBeacon("/close/" + streamId)
    })

    start()
    </script>
    </body>
    </html>
    """, token=token)

# ==============================
# RUN
# ==============================

if __name__ == "__main__":
    Thread(target=auto_cleanup, daemon=True).start()
    app.run(host="0.0.0.0", port=2881, debug=True)