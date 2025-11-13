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
