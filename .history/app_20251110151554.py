import os
import subprocess
import hashlib
import shutil
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

# Pengaturan auto cleanup
CLEANUP_INTERVAL = 60       # cek tiap 1 menit
EXPIRE_MINUTES = 5          # hapus folder setelah 5 menit tidak aktif


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
        "-hls_time", "4",           # tiap segmen 4 detik
        "-hls_list_size", "5",      # simpan 5 segmen terakhir (~20 detik)
        "-hls_flags", "delete_segments",
        os.path.join(output_path, "index.m3u8")
    ]

    subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def auto_cleanup_hls():
    """Hapus folder HLS yang sudah lama tidak aktif"""
    while True:
        now = datetime.now()
        for stream_id, info in list(active_streams.items()):
            age = (now - info["time"]).total_seconds() / 60
            if age > EXPIRE_MINUTES:
                folder = os.path.join(BASE_HLS_DIR, stream_id)
                try:
                    if os.path.exists(folder):
                        shutil.rmtree(folder)
                        print(f"[CLEANUP] Hapus stream {stream_id}")
                    active_streams.pop(stream_id, None)
                except Exception as e:
                    print(f"[CLEANUP ERROR] {stream_id}: {e}")
        time.sleep(CLEANUP_INTERVAL)


@app.route("/convertStream", methods=["POST"])
def convert_stream():
    """Mulai konversi stream"""
    data = request.get_json(silent=True) or request.form
    link = data.get("link", "")
    if not link:
        return jsonify({"error": "Parameter 'link' wajib diisi"}), 400

    # Buat nama output unik
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

    base_url = request.host_url.rstrip("/")  # contoh: http://127.0.0.1:5000

    return jsonify({
        "id": output_name,
        "status": "conversion_started",
        "hls_url": f"{base_url}/static/hls/{output_name}/index.m3u8",
        "player_url": f"{base_url}/play/{output_name}",
        "start_time": active_streams[output_name]["time"].strftime("%Y-%m-%d %H:%M:%S")
    })


@app.route("/streams", methods=["GET"])
def list_streams():
    """Daftar stream aktif"""
    base_url = request.host_url.rstrip("/")
    return jsonify([
        {
            "id": k,
            "source": v["source"],
            "start_time": v["time"].strftime("%Y-%m-%d %H:%M:%S"),
            "player_url": f"{base_url}/play/{k}"
        }
        for k, v in active_streams.items()
    ])


@app.route("/play/<stream_id>")
def play_stream(stream_id):
    """Tampilkan player HLS"""
    if stream_id not in active_streams:
        return f"<h2>Stream ID {stream_id} tidak ditemukan.</h2>", 404

    hls_path = os.path.join(BASE_HLS_DIR, stream_id, "index.m3u8")

    # Tunggu sampai index.m3u8 muncul (maks 10 detik)
    for _ in range(10):
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

            setTimeout(initPlayer, 3000);
        </script>
    </body>
    </html>
    """
    return render_template_string(html)


if __name__ == "__main__":
    # Jalankan auto-cleanup di background
    Thread(target=auto_cleanup_hls, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=True)
