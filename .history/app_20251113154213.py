import os
import subprocess
import hashlib
import shutil
import time
from flask import Flask, request, jsonify, render_template_string
from threading import Thread
from datetime import datetime
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ==============================
# KONFIGURASI
# ==============================
BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

CLEANUP_INTERVAL = 60      # cek setiap 1 menit
EXPIRE_MINUTES = 2        # hapus jika tidak diakses > 5 menit

# Dictionary: stream_id -> { source, time, is_played, last_access }
active_streams = {}


# ==============================
# UTILITAS
# ==============================
def get_stream_folder(stream_id: str) -> str:
    """Dapatkan path folder HLS untuk stream tertentu"""
    return os.path.join(BASE_HLS_DIR, stream_id)


def create_hls_folder(stream_id: str):
    """Pastikan folder HLS tersedia"""
    folder = get_stream_folder(stream_id)
    os.makedirs(folder, exist_ok=True)
    return folder


def run_ffmpeg_to_hls(source_url: str, stream_id: str):
    """Jalankan FFmpeg untuk mengubah stream ke HLS"""
    output_dir = create_hls_folder(stream_id)
    output_file = os.path.join(output_dir, "index.m3u8")

    cmd = [
        "ffmpeg", "-y",
        "-i", source_url,
        "-c", "copy",
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "5",
        "-hls_flags", "delete_segments",
        output_file
    ]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def remove_old_streams():
    """Hapus stream yang sudah lama tidak diakses"""
    now = datetime.now()
    for stream_id, info in list(active_streams.items()):
        last_access = info.get("last_access", info["time"])
        age_minutes = (now - last_access).total_seconds() / 60

        if age_minutes > EXPIRE_MINUTES:
            folder = get_stream_folder(stream_id)
            try:
                if os.path.exists(folder):
                    shutil.rmtree(folder)
                    print(f"[CLEANUP] Hapus stream {stream_id} (tidak diakses > {EXPIRE_MINUTES} menit)")
                active_streams.pop(stream_id, None)
            except Exception as e:
                print(f"[CLEANUP ERROR] {stream_id}: {e}")


def auto_cleanup_hls():
    """Loop background untuk auto cleanup"""
    while True:
        remove_old_streams()
        time.sleep(CLEANUP_INTERVAL)


# ==============================
# ENDPOINT API
# ==============================
@app.route("/convertStream", methods=["POST"])
def convert_stream():
    data = request.get_json(silent=True) or request.form
    link = data.get("link", "")
    if not link:
        return jsonify({"error": "Parameter 'link' wajib diisi"}), 400

    # Buat ID unik
    stream_id = hashlib.md5(link.encode()).hexdigest()[:10]

    # Jika belum aktif, jalankan FFmpeg
    if stream_id not in active_streams:
        thread = Thread(target=run_ffmpeg_to_hls, args=(link, stream_id), daemon=True)
        thread.start()
        active_streams[stream_id] = {
            "source": link,
            "time": datetime.now(),
            "is_played": False,
            "last_access": datetime.now()
        }

    base_url = request.host_url.rstrip("/")

    return jsonify({
        "id": stream_id,
        "status": "conversion_started",
        # "hls_url": f"{base_url}/static/hls/{stream_id}/index.m3u8",
        "player_url": f"{base_url}/livestream/iOS/{stream_id}",
        "start_time": active_streams[stream_id]["time"].strftime("%Y-%m-%d %H:%M:%S")
    })


@app.route("/streams")
def list_streams():
    """Tampilkan daftar stream aktif"""
    base_url = request.host_url.rstrip("/")
    return jsonify([
        {
            "id": sid,
            "source": data["source"],
            "is_played": data["is_played"],
            "last_access": data["last_access"].strftime("%Y-%m-%d %H:%M:%S"),
            "start_time": data["time"].strftime("%Y-%m-%d %H:%M:%S"),
            "player_url": f"{base_url}/play/{sid}"
        }
        for sid, data in active_streams.items()
    ])


@app.route("/livestream/iOS/<stream_id>")
def play_stream(stream_id):
    """Render halaman player HLS"""
    if stream_id not in active_streams:
        return f"<h2>Stream ID {stream_id} tidak ditemukan.</h2>", 404

    # Tandai sebagai sudah diplay dan update waktu akses terakhir
    active_streams[stream_id]["is_played"] = True
    active_streams[stream_id]["last_access"] = datetime.now()

    hls_path = os.path.join(BASE_HLS_DIR, stream_id, "index.m3u8")

    # tunggu sampai file m3u8 siap
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
            const src = '{hls_url}';
            function initPlayer() {{
                if (Hls.isSupported()) {{
                    const hls = new Hls();
                    hls.loadSource(src);
                    hls.attachMedia(video);
                    hls.on(Hls.Events.MANIFEST_PARSED, () => video.play());
                    hls.on(Hls.Events.ERROR, (e, data) => {{
                        if (data.fatal) {{
                            console.log('Retrying in 3s...');
                            setTimeout(initPlayer, 3000);
                        }}
                    }});
                }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
                    video.src = src;
                    video.addEventListener('loadedmetadata', () => video.play());
                }} else {{
                    document.body.innerHTML = '<h2 style="color:white;">Browser tidak mendukung HLS</h2>';
                }}
            }}
            setTimeout(initPlayer, 3000);

            // Kirim ping tiap 30 detik supaya dianggap aktif
            setInterval(() => {{
                fetch('/ping/{stream_id}');
            }}, 30000);
        </script>
    </body>
    </html>
    """
    return render_template_string(html)


@app.route("/ping/<stream_id>")
def ping_stream(stream_id):
    """Dipanggil otomatis dari player untuk memperbarui last_access"""
    if stream_id in active_streams:
        active_streams[stream_id]["last_access"] = datetime.now()
    return "", 204


# ==============================
# MAIN ENTRY
# ==============================
if __name__ == "__main__":
    Thread(target=auto_cleanup_hls, daemon=True).start()
    app.run(host="0.0.0.0", port=2881, debug=True)
