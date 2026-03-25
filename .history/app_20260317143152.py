import os
import subprocess
import hashlib
import shutil
import time
import requests
import re

from flask import Flask, jsonify, render_template
from threading import Thread, Lock
from datetime import datetime
from flask_cors import CORS
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)
CORS(app)

stream_lock = Lock()

# ==============================
# KONFIGURASI
# ==============================
BASE_API = "https://i-see.iconpln.co.id/backend"
BASE_HLS_DIR = os.path.join(os.path.dirname(__file__), "static", "hls")
os.makedirs(BASE_HLS_DIR, exist_ok=True)

CLEANUP_INTERVAL = 4
EXPIRE_MINUTES = 2
active_streams = {}

# ==============================
# SESSION REQUESTS
# ==============================
session = requests.Session()
retry = Retry(total=3, backoff_factor=1, status_forcelist=[500,502,503,504])
adapter = HTTPAdapter(max_retries=retry)
session.mount("http://", adapter)
session.mount("https://", adapter)

def safe_get(url, retries=3):
    for i in range(retries):
        try:
            return session.get(url, timeout=(5,10), verify=False)
        except requests.exceptions.ConnectTimeout:
            print(f"[RETRY] ConnectTimeout {i+1}/{retries}")
            time.sleep(1)
    raise Exception("API tidak bisa dihubungi (ConnectTimeout)")

# ==============================
# HELPERS
# ==============================
def get_stream_folder(stream_id):
    return os.path.join(BASE_HLS_DIR, stream_id)

def create_hls_folder(stream_id):
    folder = get_stream_folder(stream_id)
    os.makedirs(folder, exist_ok=True)
    return folder

def is_hls(url):
    return url and url.lower().endswith(".m3u8")

# ==============================
# FFMPEG → HLS
# ==============================
def run_ffmpeg_to_hls(source_url, stream_id):
    output_dir = create_hls_folder(stream_id)
    output_file = os.path.join(output_dir, "index.m3u8")
    log_file = os.path.join(output_dir, "ffmpeg.log")
    ffmpeg_path = r"C:\ffmpeg\bin\ffmpeg.exe"

    cmd = [ffmpeg_path, "-y"]
    if source_url.lower().startswith("rtsp"):
        cmd += ["-rtsp_transport", "tcp", "-stimeout", "5000000"]

    cmd += [
        "-rw_timeout", "10000000",
        "-reconnect","1","-reconnect_streamed","1","-reconnect_delay_max","5",
        "-i", source_url,
        "-c","copy",
        "-f","hls",
        "-hls_time","4",
        "-hls_list_size","5",
        "-hls_flags","delete_segments",
        output_file
    ]

    f=None; proc=None
    try:
        try: f=open(log_file,"w",encoding="utf-8")
        except: f=None
        if f: proc=subprocess.Popen(cmd,stdout=f,stderr=f)
        else: proc=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

        if stream_id in active_streams:
            active_streams[stream_id]["proc"]=proc
            active_streams[stream_id]["log_file"]=f
        proc.wait()
    except Exception as e:
        print(f"[FFMPEG ERROR] {stream_id}: {e}")
    finally:
        if f: f.close()
        if stream_id in active_streams:
            active_streams[stream_id].pop("proc",None)

# ==============================
# CLEANUP STREAMS
# ==============================
def remove_old_streams():
    now = datetime.now()
    for stream_id, info in list(active_streams.items()):
        last_access = info.get("last_access", info["time"])
        age_minutes = (now - last_access).total_seconds()/60
        viewers = info.get("viewers",0)
        if age_minutes>EXPIRE_MINUTES and viewers==0:
            folder=get_stream_folder(stream_id)
            try:
                proc=info.get("proc")
                if proc and proc.poll() is None:
                    try: proc.terminate(); proc.wait(timeout=3)
                    except: proc.kill()
                if os.path.exists(folder): time.sleep(1); shutil.rmtree(folder)
                active_streams.pop(stream_id,None)
            except Exception as e: print(f"[CLEANUP ERROR] {stream_id}: {e}")

def auto_cleanup_hls():
    while True:
        remove_old_streams()
        time.sleep(CLEANUP_INTERVAL)

# ==============================
# DEBUG STREAM
# ==============================
def debug_stream_response(url):
    try:
        r=requests.get(url,timeout=5,verify=False,stream=True)
        try: return "json", r.json()
        except: return "non-json", None
    except Exception as e:
        return "error", str(e)

# ==============================
# ENDPOINTS
# ==============================
@app.route("/")
def hello():
    return "HLS Converter is running"

@app.route("/ping/<stream_id>")
def ping(stream_id):
    path = os.path.join(BASE_HLS_DIR, stream_id, "index.m3u8")
    if os.path.exists(path): return jsonify({"status":"ready"})
    return jsonify({"status":"not_ready"}),404

@app.route("/livestream/iOS/<token>")
def play_camera(token):
    try:
        api_url = f"{BASE_API}/api/View/EmbedStaticLink?token={token}"
        resp = safe_get(api_url)
        resp.raise_for_status()
        data = resp.json()["data"][0]
        streaming_url = data.get("streamingURL")
        if not streaming_url:
            return "<h2>Stream offline / tidak tersedia</h2>"

        stream_type, debug_data = debug_stream_response(streaming_url)
        if stream_type=="json": return f"<h2>Stream ERROR (JSON): {debug_data}</h2>"
        if stream_type=="error": return f"<h2>Request gagal: {debug_data}</h2>"

        camera_id = data.get("cameraId") or token
        stream_id = hashlib.md5(str(camera_id).encode()).hexdigest()[:10]

        if is_hls(streaming_url):
            return render_template("player.html",
                hls_url=streaming_url,
                stream_id=stream_id,
                fallback_url=streaming_url,
                is_offline=False,
                error_message=""
            )
        else:
            with stream_lock:
                if stream_id not in active_streams:
                    active_streams[stream_id]={
                        "source":streaming_url,
                        "time":datetime.now(),
                        "viewers":0,
                        "last_access":datetime.now()
                    }
                    Thread(target=run_ffmpeg_to_hls,args=(streaming_url,stream_id),daemon=True).start()

            hls_path=os.path.join(BASE_HLS_DIR,stream_id,"index.m3u8")
            for i in range(10):
                if os.path.exists(hls_path): break
                time.sleep(0.5)
            if not os.path.exists(hls_path):
                return render_template("player.html",
                    hls_url="",
                    stream_id=stream_id,
                    fallback_url=streaming_url,
                    is_offline=True,
                    error_message="FFMPEG gagal / stream tidak jalan"
                )
            hls_url=f"/static/hls/{stream_id}/index.m3u8"
            return render_template("player.html",
                hls_url=hls_url,
                stream_id=stream_id,
                fallback_url=streaming_url,
                is_offline=False,
                error_message=""
            )
    except Exception as e:
        return f"<h2>Error: {e}</h2>"

# ==============================
# MAIN
# ==============================
if __name__=="__main__":
    Thread(target=auto_cleanup_hls,daemon=True).start()
    app.run(host="0.0.0.0",port=2881,debug=True)