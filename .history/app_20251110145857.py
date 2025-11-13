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
import shutil
from flask import Flask, request, jsonify, render_template_string
from threading import Thread, Lock
from datetime import datetime, timedelta

app = Flask(__name__)

BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

active_streams = {}
lock = Lock()


def cleanup_inactive_streams():
    """Hapus stream yang sudah tidak aktif (tidak ditonton 2 menit)"""
    while True:
        now = datetime.now()
        with lock:
            for sid, info in list(active_streams.items()):
                if (now - info["last_watch"]).total_seconds() > 120:
                    print(f"[CLEANUP] Hapus stream tidak aktif: {sid}")
                    proc = info.get("process")
                    if proc and proc.poll() is None:
                        proc.terminate()
                    folder = os.path.join(BASE_HLS_DIR, sid)
                    shutil.rmtree(folder, ignore_errors=True)
                    del active_streams[sid]
        time.sleep(30)


def start_ffmpeg_to_hls(source_url: str, output_name: str):
    """Jalankan ffmpeg di background untuk konversi ke HLS"""
    output_path = os.path.join(BASE_HLS_DIR, output_name)
    os.makedirs(output_path, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-i", source_url,
        "-vf", "scale=-2:720",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-f", "hls",
        "-hls_time", "3",
        "-hls_list_size", "8",
        "-hls_flags", "delete_segments+append_list+program_date_time",
        os.path.join(output_path, "index.m3u8")
    ]

    print(f"[FFMPEG] Start: {source_url}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    active_streams[output_name]["process"] = proc
    proc.wait()

    # Bersihkan jika proses selesai
    if os.path.exists(output_path):
        shutil.rmtree(output_path, ignore_errors=True)
    with lock:
        if output_name in active_streams:
            del active_streams[output_name]


@app.route("/convertStream", methods=["POST"])
def convert_stream():
    """Mulai download stream di background"""
    data = request.get_json(silent=True) or request.form
    link = data.get("link", "")
    if not link:
        return jsonify({"error": "Parameter 'link' wajib diisi"}), 400

    sid = hashlib.md5(link.encode()).hexdigest()[:10]
    output_path = os.path.join(BASE_HLS_DIR, sid)

    with lock:
        if sid not in active_streams:
            os.makedirs(output_path, exist_ok=True)
            active_streams[sid] = {
                "source": link,
                "time": datetime.now(),
                "last_watch": datetime.now(),
                "process": None
            }
            thread = Thread(target=start_ffmpeg_to_hls, args=(link, sid), daemon=True)
            thread.start()

    return jsonify({
        "id": sid,
        "status": "started",
        "player_url": f"/play/{sid}",
        "hls_url": f"/static/hls/{sid}/index.m3u8"
    })


@app.route("/play/<stream_id>")
def play_stream(stream_id):
    """Player HLS streaming"""
    with lock:
        if stream_id not in active_streams:
            return f"<h2>Stream {stream_id} tidak ditemukan.</h2>", 404
        active_streams[stream_id]["last_watch"] = datetime.now()

    hls_path = os.path.join(BASE_HLS_DIR, stream_id, "index.m3u8")
    for _ in range(10):
        if os.path.exists(hls_path):
            break
        time.sleep(1)

    if not os.path.exists(hls_path):
        return "<h2>Menyiapkan stream... tunggu 3–5 detik.</h2>", 503

    hls_url = f"/static/hls/{stream_id}/index.m3u8"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Live Stream {stream_id}</title>
        <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
        <style>
            body {{
                background: #000;
                color: white;
                margin: 0;
                padding: 0;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                height: 100vh;
            }}
            video {{
                width: 80%;
                max-width: 900px;
                border-radius: 10px;
                box-shadow: 0 0 20px rgba(0,0,0,0.6);
            }}
        </style>
    </head>
    <body>
        <h3>Live Stream ID: {stream_id}</h3>
        <video id="video" controls autoplay muted></video>
        <script>
            const video = document.getElementById('video');
            const src = '{hls_url}';
            if (Hls.isSupported()) {{
                const hls = new Hls({{ lowLatencyMode: true }});
                hls.loadSource(src);
                hls.attachMedia(video);
                hls.on(Hls.Events.MANIFEST_PARSED, () => video.play());
                hls.on(Hls.Events.ERROR, (_, data) => {{
                    if (data.fatal) {{
                        setTimeout(() => location.reload(), 3000);
                    }}
                }});
            }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
                video.src = src;
                video.addEventListener('loadedmetadata', () => video.play());
            }}
        </script>
    </body>
    </html>
    """
    return render_template_string(html)


@app.route("/streams")
def list_streams():
    """List semua stream aktif"""
    with lock:
        result = []
        for sid, v in active_streams.items():
            result.append({
                "id": sid,
                "source": v["source"],
                "started": v["time"].strftime("%Y-%m-%d %H:%M:%S"),
                "last_watch": v["last_watch"].strftime("%H:%M:%S"),
                "player_url": f"/play/{sid}",
                "hls_url": f"/static/hls/{sid}/index.m3u8"
            })
    return jsonify(result)


if __name__ == "__main__":
    # Bersihkan sisa folder lama
    shutil.rmtree(BASE_HLS_DIR, ignore_errors=True)
    os.makedirs(BASE_HLS_DIR, exist_ok=True)

    # Thread auto cleanup
    Thread(target=cleanup_inactive_streams, daemon=True).start()

    app.run(host="0.0.0.0", port=5000, debug=True)
