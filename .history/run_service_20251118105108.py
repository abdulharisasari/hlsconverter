import os
from threading import Thread
from waitress import serve
from app import app, auto_cleanup_hls

if __name__ == "__main__":
    Thread(target=auto_cleanup_hls, daemon=True).start()
    serve(app, host="0.0.0.0", port=2881)
