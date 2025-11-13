import os
import subprocess
import hashlib
import shutil
from flask import Flask, request, render_template, jsonify
from threading import Thread
from datetime import datetime

BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="templates")

# Simpan daftar stream aktif di memori
active_streams = {}

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

@app.route("/")
def index():
    """Tampilkan daftar stream aktif"""
    streams = [
        {
            "id": k,
            "url": f"/player/{k}",
            "source": v["source"],
            "started": v["time"].strftime("%Y-%m-%d %H:%M:%S")
        }
        for k, v in active_streams.items()
    ]
    return render_template("index.html", streams=streams)

@app.route("/convert", methods=["POST"])
def convert():
    """Mulai konversi stream baru"""
    data = request.get_json()
    src = data.get("source")
    if not src:
        return jsonify({"error": "Source URL is required"}), 400

    output_name = hashlib.md5(src.encode()).hexdigest()[:10]
    output_path = os.path.join(BASE_HLS_DIR, output_name)

    if output_name not in active_streams:
        thread = Thread(target=start_ffmpeg_to_hls, args=(src, output_name))
        thread.daemon = True
        thread.start()

        active_streams[output_name] = {
            "source": src,
            "time": datetime.now(),
            "watching": 0
        }

    return jsonify({
        "message": "Conversion started",
        "id": output_name,
        "player_url": f"/player/{output_name}"
    })

@app.route("/player/<stream_id>")
def player(stream_id):
    """Tampilkan player HLS"""
    if stream_id not in active_streams:
        return "Stream tidak ditemukan atau sudah dihapus.", 404
    return render_template("player.html", stream_id=stream_id)
@app.route("/watch/<stream_id>/start", methods=["POST"])
def watch_start(stream_id):
    """Tandai stream sedang ditonton"""
    if stream_id in active_streams:
        active_streams[stream_id]["watching"] += 1
    return "", 204


@app.route("/watch/<stream_id>/stop", methods=["POST"])
def watch_stop(stream_id):
    """Kurangi penonton dan hapus stream kalau semua sudah selesai nonton"""
    if stream_id in active_streams:
        active_streams[stream_id]["watching"] -= 1
        if active_streams[stream_id]["watching"] <= 0:
            # Hapus folder HLS
            folder = os.path.join(BASE_HLS_DIR, stream_id)
            if os.path.exists(folder):
                import shutil
                shutil.rmtree(folder, ignore_errors=True)
            del active_streams[stream_id]
    return "", 204

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
