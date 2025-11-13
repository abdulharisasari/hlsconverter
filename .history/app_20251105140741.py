import os
import subprocess
from flask import Flask, request, jsonify, send_from_directory, render_template
from threading import Thread

app = Flask(__name__, static_folder="static", template_folder="templates")

BASE_HLS_DIR = os.path.join(app.static_folder, "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

# ---------------------------------------------------
# Fungsi untuk menjalankan ffmpeg ke format HLS (.m3u8)
# ---------------------------------------------------
def start_ffmpeg_to_hls(source_url: str, stream_id: str):
    output_dir = os.path.join(BASE_HLS_DIR, stream_id)
    os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, "index.m3u8")

    # Jika proses sudah berjalan untuk stream ini, hentikan dulu
    stop_ffmpeg_process(stream_id)

    # Command ffmpeg untuk ubah ke HLS
    cmd = [
        "ffmpeg",
        "-y",                   # overwrite
        "-i", source_url,       # input stream/video
        "-c:v", "copy",         # tidak transcode ulang (lebih ringan)
        "-c:a", "aac",
        "-f", "hls",
        "-hls_time", "5",       # durasi tiap segmen 5 detik
        "-hls_list_size", "6",  # hanya simpan segmen terakhir
        "-hls_flags", "delete_segments+append_list",
        "-hls_allow_cache", "0",
        output_path
    ]

    # Jalankan ffmpeg di thread terpisah
    def run_ffmpeg():
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    thread = Thread(target=run_ffmpeg, daemon=True)
    thread.start()

    print(f"[FFMPEG] HLS started for {stream_id} from {source_url}")


# ---------------------------------------------------
# Fungsi untuk menghentikan ffmpeg jika ada proses lama
# ---------------------------------------------------
def stop_ffmpeg_process(stream_id: str):
    # (opsional) kamu bisa tambah logika lebih kompleks di sini
    pass


# ---------------------------------------------------
# Endpoint untuk mulai konversi
# ---------------------------------------------------
@app.route("/start", methods=["POST"])
def start_conversion():
    data = request.get_json(force=True)
    source = data.get("source")
    stream_id = data.get("stream_id", "stream1")

    if not source:
        return jsonify({"ok": False, "msg": "Source URL tidak boleh kosong"})

    start_ffmpeg_to_hls(source, stream_id)

    manifest_url = f"/static/hls/{stream_id}/index.m3u8"
    return jsonify({"ok": True, "manifest_url": manifest_url})


# ---------------------------------------------------
# Route utama untuk UI
# ---------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------
# MIME type agar streaming tidak terdownload
# ---------------------------------------------------
@app.after_request
def add_headers(response):
    if response.mimetype == "application/octet-stream":
        if response.request.path.endswith(".m3u8"):
            response.mimetype = "application/vnd.apple.mpegurl"
        elif response.request.path.endswith(".ts"):
            response.mimetype = "video/mp2t"
    return response


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
