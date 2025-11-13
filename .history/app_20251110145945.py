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

import os
import subprocess
import hashlib
import time
from flask import Flask, request, jsonify, render_template_string
from threading import Thread
from datetime import datetime

app = Flask(__name__)

# Folder output HLS
BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

# Data stream aktif
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
        "-hls_time", "4",           # setiap segmen 4 detik
        "-hls_list_size", "5",      # simpan 5 segmen terakhir (≈20 detik)
        "-hls_flags", "delete_segments",
        os.path.join(output_path, "index.m3u8")
    ]

    subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@app.route("/convertStream", methods=["POST"])
def convert_stream():
    """Endpoint untuk memulai konversi stream"""
    data = request.get_json(silent=True) or request.form
    link = data.get("link", "")
    if not link:
        return jsonify({"error": "Parameter 'link' wajib diisi"}), 400

    # Buat nama output unik berdasarkan URL
    output_name = hashlib.md5(link.encode()).hexdigest()[:10]
    output_path = os.path.join(BASE_HLS_DIR, output_name)

    # Jalankan konversi jika belum ada
    if output_name not in active_streams:
        thread = Thread(target=start_ffmpeg_to_hls, args=(link, output_name))
        thread.daemon = True
        thread.start()

        active_streams[output_name] = {
            "source": link,
            "time": datetime.now()
        }

    return jsonify({
        "id": output_name,
        "status": "conversion_started",
        "hls_url": f"/static/hls/{output_name}/index.m3u8",
        "player_url": f"/play/{output_name}",
        "start_time": active_streams[output_name]["time"].strftime("%Y-%m-%d %H:%M:%S")
    })


@app.route("/streams", methods=["GET"])
def list_streams():
    """Daftar stream aktif"""
    return jsonify([
        {
            "id": k,
            "source": v["source"],
            "start_time": v["time"].strftime("%Y-%m-%d %H:%M:%S"),
            "hls_url": f"/static/hls/{k}/index.m3u8",
            "player_url": f"/play/{k}"
        }
        for k, v in active_streams.items()
    ])


@app.route("/play/<stream_id>")
def play_stream(stream_id):
    """Tampilkan player HLS, tunggu sampai index.m3u8 tersedia"""
    if stream_id not in active_streams:
        return f"<h2>Stream ID {stream_id} tidak ditemukan.</h2>", 404

    hls_path = os.path.join(BASE_HLS_DIR, stream_id, "index.m3u8")

    # Tunggu sampai file index.m3u8 muncul (maks 10 detik)
    for i in range(10):
        if os.path.exists(hls_path):
            break
        time.sleep(1)

    if not os.path.exists(hls_path):
        return f"<h2>Stream {stream_id} belum siap. Coba lagi beberapa detik lagi.</h2>", 503

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
        <video id="video" controls autoplay></video>
        <script>
            const video = document.getElementById('video');
            const videoSrc = '{hls_url}';

            function initPlayer() {{
                if (Hls.isSupported()) {{
                    const hls = new Hls();
                    hls.loadSource(videoSrc);
                    hls.attachMedia(video);
                    hls.on(Hls.Events.MANIFEST_PARSED, () => video.play());
                    hls.on(Hls.Events.ERROR, (event, data) => {{
                        if (data.fatal) {{
                            console.log('Retrying in 3s...');
                            setTimeout(initPlayer, 3000);
                        }}
                    }});
                }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
                    video.src = videoSrc;
                    video.addEventListener('loadedmetadata', () => video.play());
                }} else {{
                    document.body.innerHTML = '<h2 style="color:white;">Browser tidak mendukung HLS</h2>';
                }}
            }}

            // Tambahkan sedikit delay agar segmen awal siap
            setTimeout(initPlayer, 3000);
        </script>
    </body>
    </html>
    """
    return render_template_string(html)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
