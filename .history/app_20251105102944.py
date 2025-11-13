import os
import subprocess
import hashlib
from flask import Flask, request, jsonify, render_template
from threading import Thread

# === Konfigurasi dasar ===
BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="templates")


def generate_output_name(source_url: str) -> str:
    """Buat nama folder unik berdasarkan URL"""
    return hashlib.md5(source_url.encode()).hexdigest()[:8]


def start_ffmpeg_to_hls(source_url: str, output_name: str):
    """Jalankan FFmpeg untuk konversi live stream ke HLS"""
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
        "-hls_flags", "delete_segments+append_list",
        os.path.join(output_path, "index.m3u8")
    ]

    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ======================
# Halaman Converter
# ======================
@app.route("/")
def converter():
    return render_template("converter.html")


@app.route("/start", methods=["POST"])
def start():
    data = request.get_json()
    src = data.get("source")
    if not src:
        return jsonify({"error": "Source URL is required"}), 400

    output_name = generate_output_name(src)

    thread = Thread(target=start_ffmpeg_to_hls, args=(src, output_name))
    thread.daemon = True
    thread.start()

    return jsonify({
        "message": "Streaming started!",
        "player_url": f"/player/{output_name}",
        "hls_path": f"/static/hls/{output_name}/index.m3u8"
    })


# ======================
# Halaman Player
# ======================
@app.route("/player/<stream_id>")
def player(stream_id):
    return render_template("player.html", stream_id=stream_id)


# ======================
# Jalankan Flask
# ======================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
