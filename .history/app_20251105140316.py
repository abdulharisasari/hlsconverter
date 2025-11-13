import os
import subprocess
import uuid
from flask import Flask, request, jsonify, render_template
from threading import Thread

BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="templates")

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

    print(f"[DEBUG] Jalankan FFmpeg untuk: {source_url}")
    print(" ".join(cmd))
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    # tampilkan log FFmpeg di terminal
    for line in process.stderr:
        print("[FFmpeg]", line.strip())

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

    stream_id = uuid.uuid4().hex[:8]
    thread = Thread(target=start_ffmpeg_to_hls, args=(src, stream_id))
    thread.daemon = True
    thread.start()

    return jsonify({
        "message": "Streaming started!",
        "player_url": f"/player/{stream_id}",
        "stream_id": stream_id
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
