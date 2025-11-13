# import os
# import subprocess
# from flask import Flask, request, render_template, jsonify
# from threading import Thread

# BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
# os.makedirs(BASE_HLS_DIR, exist_ok=True)

# app = Flask(__name__, static_folder="static", template_folder="templates")

# def start_ffmpeg_to_hls(source_url: str, output_name: str):
#     """Jalankan FFmpeg untuk ubah source ke HLS"""
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


# @app.route("/")
# def index():
#     return render_template("index.html")

# @app.route("/convert", methods=["POST"])
# def convert():
#     data = request.get_json()
#     src = data.get("source")
#     if not src:
#         return jsonify({"error": "Source URL is required"}), 400

#     output_name = "live"
#     thread = Thread(target=start_ffmpeg_to_hls, args=(src, output_name))
#     thread.daemon = True
#     thread.start()

#     return jsonify({
#         "message": "Conversion started",
#         "hls_url": f"/static/hls/{output_name}/index.m3u8"
#     })

# if __name__ == "__main__":
#     app.run(host="0.0.0.0", port=5000, debug=True)



# import os
# import subprocess
# from flask import Flask, request, jsonify, render_template
# from threading import Thread

# BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
# os.makedirs(BASE_HLS_DIR, exist_ok=True)

# app = Flask(__name__, static_folder="static", template_folder="templates")

# def start_ffmpeg_to_hls(source_url: str, output_name: str):
#     """Konversi source live stream ke HLS (real-time)"""
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

# @app.route("/")
# def index():
#     return render_template("player.html")

# @app.route("/convert", methods=["POST"])
# def convert():
#     data = request.get_json()
#     src = data.get("source")
#     if not src:
#         return jsonify({"error": "Source URL is required"}), 400

#     output_name = "live"
#     thread = Thread(target=start_ffmpeg_to_hls, args=(src, output_name))
#     thread.daemon = True
#     thread.start()

#     # Return link player page untuk semua browser
#     return jsonify({
#         "message": "Conversion started",
#         "player_url": f"http://{request.host}/"
#     })

# if __name__ == "__main__":
#     app.run(host="0.0.0.0", port=5000, debug=True)



import os
import subprocess
from flask import Flask, request, jsonify, render_template
from threading import Thread

BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="templates")

def start_ffmpeg_to_hls(source_url: str, output_name: str):
    """Jalankan FFmpeg untuk konversi ke HLS"""
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

    # Kembalikan URL player page
    return jsonify({
        "message": "Conversion started",
        "player_url": f"http://{request.host}/player"
    })

@app.route("/player")
def player():
    # Halaman video hanya
    return render_template("player.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
