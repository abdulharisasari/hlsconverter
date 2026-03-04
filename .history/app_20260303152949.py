

import os
import subprocess
import hashlib
import shutil
import time
import requests
import re
from flask import Flask, request, jsonify, render_template_string
from threading import Thread
from datetime import datetime
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ==============================
# KONFIGURASI
# ==============================
BASE_API = "https://192.168.62.170:7246"

BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

CLEANUP_INTERVAL = 60
EXPIRE_MINUTES = 2

active_streams = {}

# ==============================
# UTILITAS
# ==============================

def get_stream_folder(stream_id: str) -> str:
    return os.path.join(BASE_HLS_DIR, stream_id)


def create_hls_folder(stream_id: str):
    folder = get_stream_folder(stream_id)
    os.makedirs(folder, exist_ok=True)
    return folder


def is_hls(url: str) -> bool:
    return ".m3u8" in url.lower()


def run_ffmpeg_to_hls(source_url: str, stream_id: str):
    output_dir = create_hls_folder(stream_id)
    output_file = os.path.join(output_dir, "index.m3u8")
    log_file = os.path.join(output_dir, "ffmpeg.log")

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

    with open(log_file, "w", encoding="utf-8") as f:
        subprocess.Popen(cmd, stdout=f, stderr=f)


def remove_old_streams():
    now = datetime.now()
    for stream_id, info in list(active_streams.items()):
        last_access = info.get("last_access", info["time"])
        age_minutes = (now - last_access).total_seconds() / 60

        if age_minutes > EXPIRE_MINUTES:
            folder = get_stream_folder(stream_id)
            try:
                if os.path.exists(folder):
                    shutil.rmtree(folder)
                active_streams.pop(stream_id, None)
                print(f"[CLEANUP] Stream {stream_id} dihapus")
            except Exception as e:
                print(f"[CLEANUP ERROR] {stream_id}: {e}")


def auto_cleanup_hls():
    while True:
        remove_old_streams()
        time.sleep(CLEANUP_INTERVAL)

# ==============================
# ENDPOINT
# ==============================

@app.route("/")
def hello():
    return "HLS Converter is running"



def generate_token(camera_id):
    api_url = f"{BASE_API}/api/View/GenerateCameraLink?cameraId={camera_id}"
    resp = requests.get(api_url, timeout=5, verify=False)
    resp.raise_for_status()

    data = resp.json()
    raw_streaming_url = data.get("streamingURL")

    if not raw_streaming_url:
        raise Exception("streamingURL tidak ditemukan")

    match = re.search(r"token=([^&]+)", raw_streaming_url)
    if not match:
        raise Exception("Token tidak ditemukan")

    return match.group(1)


@app.route("/generateLinkIOS")
def generate_link_ios():
    camera_id = request.args.get("cameraId")
    if not camera_id:
        return jsonify({"error": "cameraId wajib diisi"}), 400

    try:
        token = generate_token(camera_id)

        return jsonify({
            "cameraId": camera_id,
            "streamingUrl": f"{request.host_url}/livestream/iOS/{token}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/livestream/iOS/<token>")
def play_camera(token):

    # stream_id berdasarkan token (hashed agar aman untuk folder)
    stream_id = hashlib.md5(token.encode()).hexdigest()[:10]

    # ===============================
    # Ambil streamingURL dari API
    # ===============================
    try:
        api_url = f"https://192.168.62.170:7246/api/View/EmbedStaticLink?token={token}"
        resp = requests.get(api_url, timeout=5, verify=False)
        resp.raise_for_status()
        json_data = resp.json()
        streaming_url = json_data["data"][0]["streamingURL"]
    except Exception as e:
        return f"<h2>Gagal ambil streamingURL: {e}</h2>", 500

    # ===============================
    # Jika HLS langsung play
    # ===============================
    if is_hls(streaming_url):
        hls_url = streaming_url

    # ===============================
    # Jika bukan HLS → convert
    # ===============================
    else:
        if stream_id not in active_streams:
            thread = Thread(
                target=run_ffmpeg_to_hls,
                args=(streaming_url, stream_id),
                daemon=True
            )
            thread.start()

            active_streams[stream_id] = {
                "source": streaming_url,
                "time": datetime.now(),
                "is_played": False,
                "last_access": datetime.now()
            }

        active_streams[stream_id]["last_access"] = datetime.now()
        active_streams[stream_id]["is_played"] = True

        hls_url = f"/static/hls/{stream_id}/index.m3u8"

    # ===============================
    # HTML PLAYER
    # ===============================
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Live Stream</title>
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
                max-width: 900px;
                border-radius: 12px;
            }}
        </style>
    </head>
    <body>
        <video id="video" controls autoplay muted></video>

        <div id="loading" style="display:flex;position:fixed;inset:0;align-items:center;justify-content:center;background:rgba(0,0,0,0.6);z-index:9999;">
            <div style="text-align:center;color:#fff;">
                <div class="spinner" style="width:48px;height:48px;margin:0 auto 12px;border:4px solid rgba(255,255,255,0.2);border-top-color:#fff;border-radius:50%;animation:spin 1s linear infinite"></div>
                <div id="loadingText">Loading stream...</div>
            </div>
        </div>

        <style>
            @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        </style>

    <script>
        const video = document.getElementById('video');
        let src = "{hls_url}";
        const streamId = "{stream_id}";
        const token = "{token}";
        let hlsInstance = null;
        let playerStarted = false;

        const loadingEl = document.getElementById('loading');
        function showLoading(text) {{
            if (loadingEl) {{
                const t = document.getElementById('loadingText');
                if (t && text) t.textContent = text;
                loadingEl.style.display = 'flex';
            }}
        }}
        function hideLoading() {{
            if (loadingEl) loadingEl.style.display = 'none';
        }}

        async function checkReady() {{
            if (playerStarted) return;
            showLoading('Waiting for stream...');
            try {{
                const res = await fetch("/stream-ready/" + streamId);
                const data = await res.json();

                if (data.ready) {{
                    playerStarted = true;
                    hideLoading();
                    startPlayer(src);
                }} else {{
                    setTimeout(checkReady, 1000);
                }}
            }} catch (e) {{
                setTimeout(checkReady, 1000);
            }}
        }}

        function startPlayer(startSrc) {{
            const finalSrc = startSrc || src;
            hideLoading();
            if (Hls.isSupported()) {{
                if (hlsInstance) hlsInstance.destroy();
                hlsInstance = new Hls({{ lowLatencyMode: true }});
                hlsInstance.loadSource(finalSrc);
                hlsInstance.attachMedia(video);
            }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
                video.src = finalSrc;
            }} else {{
                document.body.innerHTML = '<h2 style="color:white;">Browser tidak mendukung HLS</h2>';
            }}
        }}

        function updateSource(newSrc) {{
            if (!newSrc) return;
            if (newSrc === src) return;
            src = newSrc;
            showLoading('Reloading stream...');

            if (newSrc.includes('.m3u8')) {{
                // try to start immediately; if server still processing, stream-ready check will handle it
                startPlayer(newSrc);
            }} else {{
                // Not a direct HLS URL — navigate to the new page (will trigger server conversion if needed)
                window.location.href = newSrc;
            }}
        }}

        if (src && src.startsWith("http") && src.includes(".m3u8")) {{
            startPlayer(src);
            playerStarted = true;
        }} else {{
            checkReady();
        }}

        // Poll to renew the stream every 2 minutes and replace player source when changed
        setInterval(async () => {{
            try {{
                const res = await fetch('/renew_stream/' + token);
                if (!res.ok) return;
                const data = await res.json();
                if (data && data.streamingUrl) {{
                    // if server returned a page route (e.g. /livestream/iOS/<token>) we should follow it
                    updateSource(data.streamingUrl);
                }}
            }} catch (e) {{
                // ignore errors silently
            }}
        }}, 120000);

        setInterval(() => {{
            fetch('/ping/' + streamId);
        }}, 30000);
    </script>
    </body>
    </html>
    """

    return render_template_string(html)


@app.route("/ping/<stream_id>")
def ping_stream(stream_id):
    if stream_id in active_streams:
        active_streams[stream_id]["last_access"] = datetime.now()
    return "", 204


@app.route("/streams")
def list_streams():
    return jsonify(active_streams)

@app.route("/stream-ready/<stream_id>")
def stream_ready(stream_id):
    index_file = os.path.join(get_stream_folder(stream_id), "index.m3u8")
    if os.path.exists(index_file):
        return jsonify({"ready": True})
    return jsonify({"ready": False})


@app.route("/renew_stream/<token>")
def renew_stream(token):
    """
    Try to renew the streaming URL for a given token.
    If the EmbedStaticLink response contains a camera id, generate a fresh token
    using the GenerateCameraLink endpoint and return the fresh streaming URL.
    Otherwise return the streamingURL obtained from EmbedStaticLink.
    """
    try:
        api_url = f"https://192.168.62.170:7246/api/View/EmbedStaticLink?token={token}"
        resp = requests.get(api_url, timeout=5, verify=False)
        resp.raise_for_status()
        json_data = resp.json()
        data0 = (json_data.get("data") or [{}])[0]
        streaming_url = data0.get("streamingURL")

        # try to find camera id in known keys
        camera_id = None
        for k in ("cameraId", "cameraID", "camera_id", "CameraId"):
            if k in data0:
                camera_id = data0.get(k)
                break

        if camera_id:
            try:
                new_token = generate_token(camera_id)
                # attempt to resolve the fresh streaming URL
                api_url2 = f"https://192.168.62.170:7246/api/View/EmbedStaticLink?token={new_token}"
                resp2 = requests.get(api_url2, timeout=5, verify=False)
                resp2.raise_for_status()
                json2 = resp2.json()
                data02 = (json2.get("data") or [{}])[0]
                new_streaming_url = data02.get("streamingURL") or streaming_url

                return jsonify({"streamingUrl": new_streaming_url, "token": new_token})
            except Exception:
                # fallback to original streaming_url
                return jsonify({"streamingUrl": streaming_url, "token": token})

        return jsonify({"streamingUrl": streaming_url, "token": token})
    except Exception as e:
        return jsonify({"error": str(e), "streamingUrl": None}), 500

# ==============================
# MAIN
# ==============================

# if __name__ == "__main__":
#     from waitress import serve

#     Thread(target=auto_cleanup_hls, daemon=True).start()

#     serve(app, host="0.0.0.0", port=2881)

if __name__ == "__main__":
    from waitress import serve
    Thread(target=auto_cleanup_hls, daemon=True).start()

    app.run(host="0.0.0.0", port=2881, debug=True)
