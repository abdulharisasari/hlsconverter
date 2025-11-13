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
import time
from flask import Flask, request, jsonify, render_template_string
from threading import Thread
from datetime import datetime

app = Flask(__name__)

BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

active_streams = {}

def start_ffmpeg_to_hls(source_url: str, output_name: str):
    """Jalankan FFmpeg realtime saat user nonton"""
    output_path = os.path.join(BASE_HLS_DIR, output_name)
    os.makedirs(output_path, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", source_url,
        "-vf", "scale=-2:720",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-c:a", "aac",
        "-b:v", "2500k",
        "-b:a", "128k",
        "-g", "48",                  # kontrol keyframe (6 detik pada 8fps)
        "-force_key_frames", "expr:gte(t,n_forced*4)",  # paksa keyframe tiap 4 detik
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "5",
        "-hls_flags", "delete_segments+append_list",
        os.path.join(output_path, "index.m3u8")
    ]


    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    active_streams[output_name]["process"] = process
    process.wait()

    # Kalau ffmpeg berhenti, hapus foldernya
    if os.path.exists(output_path):
        import shutil
        shutil.rmtree(output_path, ignore_errors=True)
    active_streams.pop(output_name, None)


@app.route("/convertStream", methods=["POST"])
def convert_stream():
    """Daftarkan stream tanpa langsung jalan"""
    data = request.get_json(silent=True) or request.form
    link = data.get("link", "")
    if not link:
        return jsonify({"error": "Parameter 'link' wajib diisi"}), 400

    stream_id = hashlib.md5(link.encode()).hexdigest()[:10]
    active_streams[stream_id] = {
        "source": link,
        "time": datetime.now(),
        "watching": 0,
        "process": None
    }

    return jsonify({
        "id": stream_id,
        "status": "registered",
        "player_url": f"/play/{stream_id}"
    })


@app.route("/play/<stream_id>")
def play_stream(stream_id):
    """Start ffmpeg hanya kalau player dibuka"""
    if stream_id not in active_streams:
        return f"<h2>Stream ID {stream_id} tidak ditemukan.</h2>", 404

    stream = active_streams[stream_id]
    output_path = os.path.join(BASE_HLS_DIR, stream_id)
    hls_file = os.path.join(output_path, "index.m3u8")

    # Start ffmpeg kalau belum jalan
    if stream["process"] is None or stream["process"].poll() is not None:
        thread = Thread(target=start_ffmpeg_to_hls, args=(stream["source"], stream_id))
        thread.daemon = True
        thread.start()
        print(f"[INFO] Start streaming: {stream['source']}")

    # Tunggu segmen awal siap
    for _ in range(10):
        if os.path.exists(hls_file):
            break
        time.sleep(1)

    if not os.path.exists(hls_file):
        return "<h2>Menyiapkan stream... mohon tunggu 5–10 detik.</h2>", 503

    hls_url = f"/static/hls/{stream_id}/index.m3u8"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Live Stream {stream_id}</title>
        <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
        <style>
            body {{
                background: #000;
                display: flex;
                align-items: center;
                justify-content: center;
                height: 100vh;
                margin: 0;
            }}
            video {{
                width: 80%;
                max-width: 800px;
                border-radius: 12px;
                box-shadow: 0 0 20px rgba(0,0,0,0.5);
            }}
        </style>
    </head>
    <body>
        <video id="video" controls autoplay muted></video>
        <script>
            const video = document.getElementById('video');
            const videoSrc = '{hls_url}';
            function initPlayer() {{
                if (Hls.isSupported()) {{
                    const hls = new Hls();
                    hls.loadSource(videoSrc);
                    hls.attachMedia(video);
                    hls.on(Hls.Events.MANIFEST_PARSED, () => video.play());
                }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
                    video.src = videoSrc;
                    video.addEventListener('loadedmetadata', () => video.play());
                }}
            }}
            setTimeout(initPlayer, 2000);
        </script>
    </body>
    </html>
    """
    return render_template_string(html)


@app.route("/stop/<stream_id>", methods=["POST"])
def stop_stream(stream_id):
    """Stop streaming manual"""
    if stream_id in active_streams:
        proc = active_streams[stream_id].get("process")
        if proc:
            proc.terminate()
        folder = os.path.join(BASE_HLS_DIR, stream_id)
        if os.path.exists(folder):
            import shutil
            shutil.rmtree(folder, ignore_errors=True)
        del active_streams[stream_id]
        return jsonify({"stopped": True})
    return jsonify({"error": "stream not found"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
