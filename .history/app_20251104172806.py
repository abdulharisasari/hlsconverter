import os
import subprocess
from flask import Flask, request, jsonify, render_template
from threading import Thread
from pyngrok import ngrok, conf

# ======================
# Konfigurasi HLS
# ======================
BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

# ======================
# Flask app
# ======================
app = Flask(__name__, static_folder="static", template_folder="templates")

# ======================
# Fungsi konversi live stream ke HLS
# ======================
def start_ffmpeg_to_hls(source_url: str, output_name: str):
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
    subprocess.Popen(cmd)

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

    output_name = "live"
    thread = Thread(target=start_ffmpeg_to_hls, args=(src, output_name))
    thread.daemon = True
    thread.start()

    # Ambil URL ngrok secara otomatis
    tunnels = ngrok.get_tunnels()
    public_url = tunnels[0].public_url if tunnels else None

    return jsonify({
        "message": "Streaming started!",
        "player_url": f"{public_url}/player" if public_url else "/player"
    })

# ======================
# Halaman Player
# ======================
@app.route("/player")
def player():
    return render_template("player.html")

# ======================
# Jalankan Flask + Ngrok
# ======================
if __name__ == "__main__":
    port = 5000

    # Start ngrok tunnel otomatis
    public_url = ngrok.connect(port)
    print("Ngrok tunnel URL:", public_url)

    # Jalankan Flask
    app.run(host="0.0.0.0", port=port, debug=True)
