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
from threading import Thread
from datetime import datetime

app = Flask(__name__)

# Folder output HLS
BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

active_stream = {
    "id": "",
    "source": "",
    "process": None,
    "started": None
}


def cleanup_old_stream():
    """Hapus semua folder HLS lama"""
    for folder in os.listdir(BASE_HLS_DIR):
        folder_path = os.path.join(BASE_HLS_DIR, folder)
        if os.path.isdir(folder_path):
            shutil.rmtree(folder_path, ignore_errors=True)


def start_ffmpeg_to_hls(source_url: str, output_name: str):
    """Jalankan FFmpeg realtime ke HLS"""
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
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "6",
        "-hls_flags", "delete_segments+append_list",
        os.path.join(output_path, "index.m3u8")
    ]

    print(f"[FFMPEG] Start streaming: {source_url}")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    active_stream["process"] = process
    process.wait()

    if os.path.exists(output_path):
        shutil.rmtree(output_path, ignore_errors=True)
    active_stream.update({"id": "", "source": "", "process": None})
    print("[FFMPEG] Stream stopped & cleaned.")


@app.route("/convertStream", methods=["POST"])
def convert_stream():
    """Daftarkan stream baru"""
    data = request.get_json(silent=True) or request.form
    link = data.get("link", "")
    if not link:
        return jsonify({"error": "Parameter 'link' wajib diisi"}), 400

    stream_id = hashlib.md5(link.encode()).hexdigest()[:10]

    # stop stream lama
    old_proc = active_stream.get("process")
    if old_proc and old_proc.poll() is None:
        print("[INFO] Stop old stream before starting new one.")
        old_proc.terminate()
        cleanup_old_stream()

    active_stream.update({
        "id": stream_id,
        "source": link,
        "started": datetime.now(),
        "process": None
    })

    return jsonify({
        "id": stream_id,
        "status": "registered",
        "player_url": f"/play/{stream_id}"
    })


@app.route("/play/<stream_id>")
def play_stream(stream_id):
    """Tampilkan player & mulai ffmpeg jika belum jalan"""
    if stream_id != active_stream["id"]:
        return "<h2>Stream belum tersedia atau sudah diganti.</h2>", 404

    output_path = os.path.join(BASE_HLS_DIR, stream_id)
    hls_file = os.path.join(output_path, "index.m3u8")

    # Mulai FFmpeg bila belum aktif
    if not active_stream["process"] or active_stream["process"].poll() is not None:
        cleanup_old_stream()
        Thread(target=start_ffmpeg_to_hls, args=(active_stream["source"], stream_id), daemon=True).start()

    # Tunggu sampai file index.m3u8 terbentuk dan ukurannya > 0
    wait_start = time.time()
    while time.time() - wait_start < 25:
        if os.path.exists(hls_file) and os.path.getsize(hls_file) > 0:
            break
        time.sleep(1)

    # Kalau belum juga ada, tampilkan pesan auto-refresh
    if not os.path.exists(hls_file):
        html_loading = f"""
        <html>
        <head>
            <meta http-equiv="refresh" content="3">
            <title>Loading Stream...</title>
            <style>
                body {{ background:black; color:white; text-align:center; font-family:sans-serif; }}
                h2 {{ margin-top:20%; }}
            </style>
        </head>
        <body>
            <h2>Menyiapkan stream... mohon tunggu beberapa detik.</h2>
            <p>Stream ID: {stream_id}</p>
        </body>
        </html>
        """
        return render_template_string(html_loading), 503

    # Kalau sudah siap → tampilkan player
    hls_url = f"/static/hls/{stream_id}/index.m3u8"
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Live Stream</title>
        <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
        <style>
            body {{
                background:#000;
                display:flex;
                align-items:center;
                justify-content:center;
                height:100vh;
                margin:0;
            }}
            video {{
                width:85%;
                max-width:900px;
                border-radius:12px;
                box-shadow:0 0 20px rgba(0,0,0,0.5);
            }}
        </style>
    </head>
    <body>
        <video id="video" controls autoplay muted></video>
        <script>
            const video = document.getElementById('video');
            const src = '{hls_url}';
            function initPlayer() {{
                if (Hls.isSupported()) {{
                    const hls = new Hls();
                    hls.loadSource(src);
                    hls.attachMedia(video);
                    hls.on(Hls.Events.MANIFEST_PARSED, () => video.play());
                }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
                    video.src = src;
                    video.addEventListener('loadedmetadata', () => video.play());
                }}
            }}
            initPlayer();
        </script>
    </body>
    </html>
    """
    return render_template_string(html)


@app.route("/stop", methods=["POST"])
def stop_stream():
    """Stop manual"""
    proc = active_stream.get("process")
    if proc and proc.poll() is None:
        proc.terminate()
    cleanup_old_stream()
    active_stream.update({"id": "", "source": "", "process": None})
    return jsonify({"status": "stopped"})


if __name__ == "__main__":
    cleanup_old_stream()
    app.run(host="0.0.0.0", port=5000, debug=True)
