# import os
# import subprocess
# import hashlib
# import shutil
# from flask import Flask, request, render_template, jsonify
# from threading import Thread
# from datetime import datetime

# BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
# os.makedirs(BASE_HLS_DIR, exist_ok=True)

# app = Flask(__name__, static_folder="static", template_folder="templates")

# # Simpan daftar stream aktif di memori
# active_streams = {}

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

#     subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# @app.route("/")
# def index():
#     """Tampilkan daftar stream aktif"""
#     streams = [
#         {
#             "id": k,
#             "url": f"/player/{k}",
#             "source": v["source"],
#             "started": v["time"].strftime("%Y-%m-%d %H:%M:%S")
#         }
#         for k, v in active_streams.items()
#     ]
#     return render_template("index.html", streams=streams)

# @app.route("/convert", methods=["POST"])
# def convert():
#     """Mulai konversi stream baru"""
#     data = request.get_json()
#     src = data.get("source")
#     if not src:
#         return jsonify({"error": "Source URL is required"}), 400

#     output_name = hashlib.md5(src.encode()).hexdigest()[:10]
#     output_path = os.path.join(BASE_HLS_DIR, output_name)

#     if output_name not in active_streams:
#         thread = Thread(target=start_ffmpeg_to_hls, args=(src, output_name))
#         thread.daemon = True
#         thread.start()

#         active_streams[output_name] = {
#             "source": src,
#             "time": datetime.now(),
#             "watching": 0
#         }

#     return jsonify({
#         "message": "Conversion started",
#         "id": output_name,
#         "player_url": f"/player/{output_name}"
#     })

# @app.route("/player/<stream_id>")
# def player(stream_id):
#     """Tampilkan player HLS"""
#     if stream_id not in active_streams:
#         return "Stream tidak ditemukan atau sudah dihapus.", 404
#     return render_template("player.html", stream_id=stream_id)
# @app.route("/watch/<stream_id>/start", methods=["POST"])
# def watch_start(stream_id):
#     """Tandai stream sedang ditonton"""
#     if stream_id in active_streams:
#         active_streams[stream_id]["watching"] += 1
#     return "", 204


# @app.route("/watch/<stream_id>/stop", methods=["POST"])
# def watch_stop(stream_id):
#     """Kurangi penonton dan hapus stream kalau semua sudah selesai nonton"""
#     if stream_id in active_streams:
#         active_streams[stream_id]["watching"] -= 1
#         if active_streams[stream_id]["watching"] <= 0:
#             # Hapus folder HLS
#             folder = os.path.join(BASE_HLS_DIR, stream_id)
#             if os.path.exists(folder):
#                 import shutil
#                 shutil.rmtree(folder, ignore_errors=True)
#             del active_streams[stream_id]
#     return "", 204

# if __name__ == "__main__":
#     app.run(host="0.0.0.0", port=5000, debug=True)

#EXTM3U
import os
import subprocess
import hashlib
import shutil
from flask import Flask, request, render_template_string, jsonify
from threading import Thread
from datetime import datetime
import time

app = Flask(__name__)

BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

active_streams = {}

HTML_PLAYER = """
<!DOCTYPE html>
<html>
<head>
    <title>Live Stream</title>
    <meta charset="utf-8" />
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
</head>
<body style="background:#000; margin:0;">
    <video id="video" controls autoplay style="width:100%; height:100%;"></video>
    <script>
        const video = document.getElementById('video');
        const hls = new Hls();
        const id = "{{ stream_id }}";
        const src = `/static/hls/${id}/index.m3u8`;
        if (Hls.isSupported()) {
            hls.loadSource(src);
            hls.attachMedia(video);
            hls.on(Hls.Events.MANIFEST_PARSED, function () {
                video.play();
            });
        } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
            video.src = src;
        }
    </script>
</body>
</html>
"""


def start_ffmpeg_to_hls(source_url: str, output_name: str):
    """Jalankan FFmpeg untuk ubah stream ke HLS (realtime, terus update)"""
    output_path = os.path.join(BASE_HLS_DIR, output_name)
    os.makedirs(output_path, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "2",
        "-i", source_url,
        "-vf", "scale=-2:720",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-c:a", "aac",
        "-b:v", "2500k",
        "-b:a", "128k",
        "-g", "48",
        "-force_key_frames", "expr:gte(t,n_forced*4)",
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "0",                       # infinite playlist (tidak berhenti)
        "-hls_flags", "append_list+delete_segments", # realtime rolling
        "-hls_delete_threshold", "10",               # hapus segmen lama
        os.path.join(output_path, "index.m3u8")
    ]

    print(f"[INFO] Start realtime streaming: {source_url}")
    process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    active_streams[output_name]["process"] = process
    process.wait()


@app.route("/convertStream", methods=["POST"])
def convert_stream():
    data = request.get_json()
    if not data or "url" not in data:
        return jsonify({"error": "Missing URL"}), 400

    url = data["url"]
    stream_id = hashlib.md5(url.encode()).hexdigest()[:10]
    stream_dir = os.path.join(BASE_HLS_DIR, stream_id)

    if stream_id not in active_streams:
        active_streams[stream_id] = {"url": url, "created": datetime.now(), "process": None}
        thread = Thread(target=start_ffmpeg_to_hls, args=(url, stream_id), daemon=True)
        thread.start()
    else:
        print(f"[INFO] Stream {stream_id} sudah aktif")

    return jsonify({"id": stream_id, "play_url": f"/play/{stream_id}"})


@app.route("/play/<stream_id>")
def play(stream_id):
    stream_path = os.path.join(BASE_HLS_DIR, stream_id, "index.m3u8")
    if not os.path.exists(stream_path):
        return jsonify({"error": "Stream belum siap, tunggu beberapa detik"}), 503
    return render_template_string(HTML_PLAYER, stream_id=stream_id)


def cleanup_old_streams():
    """Bersihkan stream lama setiap beberapa menit"""
    while True:
        now = datetime.now()
        for sid, info in list(active_streams.items()):
            age = (now - info["created"]).seconds
            if age > 600:  # hapus stream lebih dari 10 menit
                print(f"[CLEANUP] Removing old stream {sid}")
                try:
                    if info["process"]:
                        info["process"].terminate()
                    shutil.rmtree(os.path.join(BASE_HLS_DIR, sid), ignore_errors=True)
                    del active_streams[sid]
                except Exception as e:
                    print(f"[CLEANUP ERROR] {e}")
        time.sleep(60)


if __name__ == "__main__":
    Thread(target=cleanup_old_streams, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=False)
