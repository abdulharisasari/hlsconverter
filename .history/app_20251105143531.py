import os
import subprocess
import hashlib
import shutil
import time
from flask import Flask, request, render_template, jsonify
from threading import Thread, Lock

BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="templates")

active_streams = {}
lock = Lock()

def start_ffmpeg_to_hls(source_url: str, output_name: str):
    """Jalankan FFmpeg untuk ubah source ke HLS"""
    output_path = os.path.join(BASE_HLS_DIR, output_name)
    os.makedirs(output_path, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", source_url,
        "-c", "copy",
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "5",
        "-hls_flags", "delete_segments",
        os.path.join(output_path, "index.m3u8")
    ]
    subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def cleanup_inactive_streams():
    """Loop untuk hapus stream yang tidak aktif > 60 detik"""
    while True:
        time.sleep(30)
        now = time.time()
        with lock:
            inactive = [k for k, v in active_streams.items() if now - v["last_active"] > 60]
            for stream_id in inactive:
                path = os.path.join(BASE_HLS_DIR, stream_id)
                if os.path.exists(path):
                    shutil.rmtree(path, ignore_errors=True)
                del active_streams[stream_id]
                print(f"🗑️  Hapus stream tidak aktif: {stream_id}")

@app.route("/")
def index():
    with lock:
        streams = list(active_streams.values())
    return render_template("index.html", streams=streams)

@app.route("/convert", methods=["POST"])
def convert():
    data = request.get_json()
    src = data.get("source")
    if not src:
        return jsonify({"error": "Source URL is required"}), 400

    output_name = hashlib.md5(src.encode()).hexdigest()[:10]
    output_path = os.path.join(BASE_HLS_DIR, output_name)

    with lock:
        if output_name not in active_streams:
            thread = Thread(target=start_ffmpeg_to_hls, args=(src, output_name))
            thread.daemon = True
            thread.start()
            active_streams[output_name] = {
                "id": output_name,
                "url": f"/static/hls/{output_name}/index.m3u8",
                "player_url": f"/player/{output_name}",
                "source": src,
                "last_active": time.time()
            }

    return jsonify(active_streams[output_name])

@app.route("/player/<stream_id>")
def player(stream_id):
    with lock:
        if stream_id in active_streams:
            active_streams[stream_id]["last_active"] = time.time()
    return render_template("player.html", stream_id=stream_id)

# Jalankan thread pembersih otomatis
Thread(target=cleanup_inactive_streams, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
