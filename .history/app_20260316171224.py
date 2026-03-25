import os
import subprocess
import hashlib
import shutil
import time
import requests
import re
from flask import Flask, request, jsonify, render_template_string, redirect, url_for
from threading import Thread
from datetime import datetime
from flask_cors import CORS
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# optional dependency to inspect/terminate processes (helps on Windows)
try:
    import psutil
except Exception:
    psutil = None

app = Flask(__name__)
CORS(app)

# ==============================
# KONFIGURASI
# ==============================
BASE_API = "https://i-see.iconpln.co.id/backend"

BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

CLEANUP_INTERVAL = 4
EXPIRE_MINUTES = 2

active_streams = {}
token_to_camera = {}

# ==============================
# REQUEST SESSION WITH RETRY
# ==============================

session = requests.Session()

retry = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504]
)

adapter = HTTPAdapter(max_retries=retry)

session.mount("http://", adapter)
session.mount("https://", adapter)

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


def try_terminate_ffmpeg_for_folder(target_folder: str) -> bool:
    """Best-effort: find ffmpeg processes whose command line references
    the given folder and terminate/kill them. Returns True if any were
    signaled."""
    found = False
    if not psutil:
        return False

    for proc in psutil.process_iter(attrs=("name", "cmdline")):
        try:
            pname = (proc.info.get("name") or "").lower()
            if "ffmpeg" not in pname:
                continue
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if target_folder in cmdline:
                found = True
                try:
                    proc.terminate()
                except Exception:
                    pass
        except Exception:
            # ignore inspection errors
            pass

    if found:
        # allow short time for exit, then force-kill remaining
        for proc in psutil.process_iter(attrs=("name", "cmdline")):
            try:
                pname = (proc.info.get("name") or "").lower()
                cmdline = " ".join(proc.info.get("cmdline") or [])
                if "ffmpeg" in pname and target_folder in cmdline:
                    try:
                        proc.wait(timeout=3)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
            except Exception:
                pass

    return found


def run_ffmpeg_to_hls(source_url: str, stream_id: str):
    output_dir = create_hls_folder(stream_id)
    output_file = os.path.join(output_dir, "index.m3u8")
    log_file = os.path.join(output_dir, "ffmpeg.log")

    ffmpeg_path = r"C:\ffmpeg\bin\ffmpeg.exe"

    cmd = [ffmpeg_path, "-y"]

    # jika RTSP baru pakai rtsp_transport
    if source_url.lower().startswith("rtsp"):
        cmd += [
            "-rtsp_transport", "tcp",
            "-stimeout", "5000000"
        ]

    cmd += [
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-i", source_url,
        "-c", "copy",
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "5",
        "-hls_flags", "delete_segments",
        output_file
    ]

    # start ffmpeg and keep the process handle so we can terminate it later
    try:
        f = open(log_file, "w", encoding="utf-8")
        if stream_id in active_streams:
            active_streams[stream_id]["proc"] = proc
            active_streams[stream_id]["log_file"] = f
    except Exception:
        f = None

    try:
        if f:
            proc = subprocess.Popen(cmd, stdout=f, stderr=f)
        else:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if stream_id in active_streams:
            active_streams[stream_id]["proc"] = proc
            active_streams[stream_id]["log_file"] = f   # TAMBAHAN
        try:
            proc.wait()
        except Exception:
            pass

    finally:
        try:
            if f:
                f.close()
        except Exception:
            pass

        # cleanup process handle reference when ffmpeg ends
        if stream_id in active_streams:
            active_streams[stream_id].pop("proc", None)

def remove_old_streams():
    now = datetime.now()

    for stream_id, info in list(active_streams.items()):
        last_access = info.get("last_access", info["time"])
        age_minutes = (now - last_access).total_seconds() / 60

        viewers = info.get("viewers", 0)

        if age_minutes > EXPIRE_MINUTES:
            folder = get_stream_folder(stream_id)

            try:
                proc = info.get("proc")

                # ======================
                # Stop FFmpeg process
                # ======================
                if proc and proc.poll() is None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except:
                        try:
                            proc.kill()
                            proc.wait(timeout=5)
                        except:
                            pass

                # ======================
                # Close log file
                # ======================
                log_file = info.get("log_file")
                if log_file:
                    try:
                        log_file.close()
                    except:
                        pass

                # ======================
                # Delete folder
                # ======================
                if os.path.exists(folder):

                    # beri waktu OS melepas file handle
                    time.sleep(1)

                    attempts = 5
                    for i in range(attempts):
                        try:
                            shutil.rmtree(folder)
                            break
                        except PermissionError:
                            print(f"[CLEANUP] folder {stream_id} masih terkunci, retry {i+1}")
                            time.sleep(1)

                active_streams.pop(stream_id, None)
                print(f"[CLEANUP] Stream {stream_id} dihapus")

            except Exception as e:
                print(f"[CLEANUP ERROR] {stream_id}: {e}")

    # ==============================
    # Scan orphan folders
    # ==============================
    try:
        for name in os.listdir(BASE_HLS_DIR):

            folder = os.path.join(BASE_HLS_DIR, name)

            if not os.path.isdir(folder):
                continue

            if name in active_streams:
                continue

            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(folder))
            except:
                continue

            age_minutes = (now - mtime).total_seconds() / 60

            if age_minutes > EXPIRE_MINUTES:
                try:

                    # coba terminate ffmpeg yang pakai folder ini
                    try_terminate_ffmpeg_for_folder(folder)

                    attempts = 3
                    for i in range(attempts):
                        try:
                            shutil.rmtree(folder)
                            print(f"[CLEANUP] Orphan folder {name} dihapus")
                            break
                        except Exception as e:

                            if i == attempts - 1:
                                print(f"[CLEANUP ERROR] orphan {name}: {e}")
                            else:
                                time.sleep(1)

                except Exception as e:
                    print(f"[CLEANUP ERROR] orphan {name}: {e}")

    except Exception as e:
        print(f"[CLEANUP ERROR] scanning folders: {e}")
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
    # resp = session.get(api_url, timeout=30, verify=False)
    resp = session.get(api_url, timeout=(5,10), verify=False)
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
        token_to_camera[token] = camera_id

        return jsonify({
            "cameraId": camera_id,
            "streamingUrl": f"{request.host_url}livestream/iOS/{token}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/livestream/iOS/<token>")
def play_camera(token):

    stream_id = None

    try:
        api_url = f"{BASE_API}/api/View/EmbedStaticLink?token={token}"
        resp = session.get(api_url, timeout=(5,10), verify=False)
        resp.raise_for_status()

        streaming_url = None
        camera_id = None

        content_type = resp.headers.get("Content-Type","").lower()

        # ===============================
        # Jika response JSON
        # ===============================
        if "application/json" in content_type:
            try:
                json_data = resp.json()
                data0 = (json_data.get("data") or [{}])[0]

                streaming_url = data0.get("streamingURL")

                for k in ("cameraId","cameraID","camera_id","CameraId"):
                    if k in data0:
                        camera_id = data0.get(k)
                        break

            except Exception:
                streaming_url = None

        # ===============================
        # Jika bukan JSON (redirect/video)
        # ===============================
        else:
            streaming_url = resp.url

        if not streaming_url:
            return "<h2>Streaming URL tidak ditemukan</h2>",500

        print(f"[DEBUG] streaming_url: {streaming_url}")

        # ===============================
        # Generate stream_id
        # ===============================
        if camera_id:
            token_to_camera[token] = camera_id
            stream_id = hashlib.md5(str(camera_id).encode()).hexdigest()[:10]
        else:
            stream_id = hashlib.md5(token.encode()).hexdigest()[:10]


    except requests.exceptions.HTTPError as e:

        resp = getattr(e,'response',None)
        status = getattr(resp,'status_code',None)

        if status == 400:
            camera_id = token_to_camera.get(token)

            if camera_id:
                try:
                    new_token = generate_token(camera_id)
                    token_to_camera[new_token] = camera_id
                    return redirect(url_for('play_camera',token=new_token))
                except Exception as e2:
                    return f"<h2>Gagal regenerate token: {e2}</h2>",500

        return f"<h2>Gagal ambil streamingURL: {e}</h2>",500


    except (
        requests.exceptions.ReadTimeout,
        requests.exceptions.ConnectTimeout,
        requests.exceptions.ConnectionError
    ):
        return """
        <html>
        <head>
        <meta charset="UTF-8">
        <title>Connection Error</title>
        <style>
        body{
        background:#000;
        color:white;
        display:flex;
        align-items:center;
        justify-content:center;
        height:100vh;
        font-family:Arial;
        }
        </style>
        </head>
        <body>

        <div>
        <h2>Server streaming tidak merespon</h2>
        <p>Mencoba reconnect...</p>
        </div>

        <script>
        setTimeout(()=>{
        location.reload();
        },3000);
        </script>

        </body>
        </html>
        """

    # ===============================
    # Jika HLS langsung play
    # ===============================
    if is_hls(streaming_url):
        hls_url = streaming_url

    # ===============================
    # Jika bukan HLS → convert
    # ===============================
    else:

        if (
            stream_id not in active_streams
            or active_streams[stream_id].get("proc") is None
            or active_streams[stream_id]["proc"].poll() is not None
        ):

            active_streams[stream_id] = {
                "source": streaming_url,
                "time": datetime.now(),
                "is_played": False,
                "viewers": 0,
                "last_access": datetime.now()
            }

            thread = Thread(
                target=run_ffmpeg_to_hls,
                args=(streaming_url,stream_id),
                daemon=True
            )
            thread.start()

        active_streams[stream_id]["last_access"] = datetime.now()
        active_streams[stream_id]["is_played"] = True

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
    width:80%;
    max-width:900px;
    border-radius:12px;
    }}
    </style>

    </head>

    <body>

    <video id="video" controls autoplay muted></video>

    <script>

    const video = document.getElementById('video');
    let src = "{hls_url}";

    if (Hls.isSupported()) {{

        const hls = new Hls({{
        lowLatencyMode:true
        }});

        hls.loadSource(src);
        hls.attachMedia(video);

    }}
    else if(video.canPlayType('application/vnd.apple.mpegurl')) {{

        video.src = src;

    }}
    else {{

        document.body.innerHTML =
        '<h2 style="color:white">Browser tidak support HLS</h2>';

    }}

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


@app.route('/open/<stream_id>', methods=['GET', 'POST'])
def open_stream(stream_id):
    if stream_id in active_streams:
        active_streams[stream_id]['viewers'] = active_streams[stream_id].get('viewers', 0) + 1
        active_streams[stream_id]['last_access'] = datetime.now()
    else:
        # ensure an entry exists so cleanup can track it
        active_streams[stream_id] = {
            'source': None,
            'time': datetime.now(),
            'is_played': True,
            'viewers': 1,
            'last_access': datetime.now()
        }
    return "", 204


@app.route('/close/<stream_id>', methods=['GET', 'POST'])
def close_stream(stream_id):
    if stream_id in active_streams:
        info = active_streams[stream_id]

        info['viewers'] = max(0, info.get('viewers', 0) - 1)
        info['last_access'] = datetime.now()

        # jika tidak ada viewer lagi → matikan ffmpeg
        if info['viewers'] == 0:
            proc = info.get("proc")
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except:
                    pass

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
        api_url = f"{BASE_API}/api/View/EmbedStaticLink?token={token}"
        # resp = session.get(api_url, timeout=30, verify=False)
        resp = session.get(api_url, timeout=(5,10), verify=False)
        resp.raise_for_status()
        json_data = resp.json()
        data0 = (json_data.get("data") or [{}])[0]
        streaming_url = data0.get("streamingURL")

        print(f"[DEBUG]REVENUW EmbedStaticLink response data0: {data0}")
        print(f"[DEBUG] extracted streaming_url: {streaming_url}")

        # try to find camera id in known keys
        camera_id = None
        for k in ("cameraId", "cameraID", "camera_id", "CameraId"):
            if k in data0:
                camera_id = data0.get(k)
                break

        # Use the token (or regenerated token) and ensure server starts conversion when needed.
        token_used = token
        if camera_id:
            try:
                new_token = generate_token(camera_id)
                token_to_camera[new_token] = camera_id
                # try to resolve the fresh streaming URL
                api_url2 = f"{BASE_API}/api/View/EmbedStaticLink?token={new_token}"
                resp2 = session.get(api_url2, timeout=30, verify=False)
                resp2.raise_for_status()
                json2 = resp2.json()
                data02 = (json2.get("data") or [{}])[0]
                new_streaming_url = data02.get("streamingURL") or streaming_url
                token_used = new_token
                streaming_url = new_streaming_url
            except Exception:
                # fallback to original streaming_url and token
                token_used = token

        # compute stream id from camera_id when possible, otherwise token_used
        if camera_id:
            stream_id = hashlib.md5(str(camera_id).encode()).hexdigest()[:10]
        else:
            stream_id = hashlib.md5(token_used.encode()).hexdigest()[:10]

        if not is_hls(streaming_url):
            if stream_id not in active_streams:
                # create entry first so the thread can register its proc handle
                active_streams[stream_id] = {
                    "source": streaming_url,
                    "time": datetime.now(),
                    "is_played": False,
                    "viewers": 0,
                    "last_access": datetime.now()
                }
                thread = Thread(target=run_ffmpeg_to_hls, args=(streaming_url, stream_id), daemon=True)
                thread.start()
            active_streams[stream_id]["last_access"] = datetime.now()
            active_streams[stream_id]["is_played"] = True

        return jsonify({"streamingUrl": streaming_url, "token": token_used, "playerUrl": f"/livestream/iOS/{token_used}", "streamId": stream_id})
    except requests.exceptions.HTTPError as e:
        resp = getattr(e, 'response', None)
        status = getattr(resp, 'status_code', None)
        if status == 400:
            # try regenerate token if we have camera id mapping
            camera_id = token_to_camera.get(token)
            if camera_id:
                try:
                    new_token = generate_token(camera_id)
                    token_to_camera[new_token] = camera_id

                    # try fetch with new token
                    api_url2 = f"{BASE_API}/api/View/EmbedStaticLink?token={new_token}"
                    resp2 = session.get(api_url2, timeout=30, verify=False)
                    resp2.raise_for_status()
                    json2 = resp2.json()
                    d02 = (json2.get("data") or [{}])[0]
                    new_streaming_url = d02.get("streamingURL")
                    # determine stream id from camera mapping if available
                    cid = token_to_camera.get(new_token) or None
                    if cid:
                        sid = hashlib.md5(str(cid).encode()).hexdigest()[:10]
                    else:
                        sid = hashlib.md5(new_token.encode()).hexdigest()[:10]
                    return jsonify({"streamingUrl": new_streaming_url, "token": new_token, "playerUrl": f"/livestream/iOS/{new_token}", "streamId": sid})
                except Exception:
                    return jsonify({"error": "gagal regenerate token", "streamingUrl": None}), 500

        return jsonify({"error": str(e), "streamingUrl": None}), 500
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



