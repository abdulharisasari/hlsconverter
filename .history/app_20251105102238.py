

# import os
# import subprocess
# from flask import Flask, request, jsonify, render_template
# from threading import Thread
# from pyngrok import ngrok

# BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
# os.makedirs(BASE_HLS_DIR, exist_ok=True)

# app = Flask(__name__, static_folder="static", template_folder="templates")

# def start_ffmpeg_to_hls(source_url: str, output_name: str):
#     """Jalankan FFmpeg untuk konversi live stream ke HLS"""
#     output_path = os.path.join(BASE_HLS_DIR, output_name)
#     os.makedirs(output_path, exist_ok=True)
#     cmd = [
#         "ffmpeg",
#         "-y",
#         "-i", source_url,
#         "-c", "copy",
#         "-f", "hls",
#         "-hls_time", "4",
#         "-hls_list_size", "5",
#         "-hls_flags", "delete_segments",
#         os.path.join(output_path, "index.m3u8")
#     ]
#     subprocess.Popen(cmd)

# # ======================
# # Halaman Converter
# # ======================
# @app.route("/")
# def converter():
#     return render_template("converter.html")

# @app.route("/start", methods=["POST"])
# def start():
#     data = request.get_json()
#     src = data.get("source")
#     if not src:
#         return jsonify({"error": "Source URL is required"}), 400

#     output_name = "live"
#     thread = Thread(target=start_ffmpeg_to_hls, args=(src, output_name))
#     thread.daemon = True
#     thread.start()

#     return jsonify({
#         "message": "Streaming started!",
#         "player_url": f"/player"
#     })

# # ======================
# # Halaman Player
# # ======================
# @app.route("/player")
# def player():
#     return render_template("player.html")

# # ======================
# # Jalankan Flask + Ngrok
# # ======================
# if __name__ == "__main__":
#     app.run(host="0.0.0.0", port=5000, debug=True)


import os
import subprocess
from flask import Flask, request, jsonify, render_template
from threading import Thread

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

    # Masukkan PUBLIC_URL ngrok manual di sini
    PUBLIC_URL = "https://coba.ngrok-free.app"  # Ganti dengan ngrok URL setelah jalan manual
    return jsonify({
        "message": "Streaming started!",
        "player_url": f"{PUBLIC_URL}/player"
    })

# ======================
# Halaman Player
# ======================
@app.route("/player")
def player():
    # Player hanya menampilkan video HLS
    return render_template("player.html")

# ======================
# Jalankan Flask
# ======================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)