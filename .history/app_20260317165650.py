@app.route("/livestream/iOS/<token>")
def play_camera(token):

    stream_id = None

    try:
        api_url = f"{BASE_API}/api/View/EmbedStaticLink?token={token}"
        resp = requests.get(api_url, timeout=30, verify=False)
        resp.raise_for_status()
        json_data = resp.json()
        data0 = (json_data.get("data") or [{}])[0]
        streaming_url = data0.get("streamingURL")

        # compute stream_id from camera_id or token
        camera_id = data0.get("cameraId") or data0.get("cameraID") or None
        if camera_id:
            token_to_camera[token] = camera_id
            stream_id = hashlib.md5(str(camera_id).encode()).hexdigest()[:10]
        else:
            stream_id = hashlib.md5(token.encode()).hexdigest()[:10]

    except requests.exceptions.ConnectTimeout:
        return render_template_string("""
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Connection Timeout</title>
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
                <h2>Connection Timeout</h2>
                <p>Unable to connect to the server. Retrying...</p>
            </div>
            <script>
                setTimeout(()=>{ location.reload(); }, 5000);
            </script>
        </body>
        </html>
        """)
    except requests.exceptions.ReadTimeout:
        return render_template_string("""
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Read Timeout</title>
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
                <h2>Request Timeout</h2>
                <p>Server did not respond in time. Retrying...</p>
            </div>
            <script>
                setTimeout(()=>{ location.reload(); }, 5000);
            </script>
        </body>
        </html>
        """)
    except requests.exceptions.HTTPError as e:
        return f"<h2>HTTP Error: {e}</h2>", 500
    except Exception as e:
        return f"<h2>Failed to fetch streaming URL: {e}</h2>", 500

    # lanjut ke HLS check / convert seperti sebelumnya
    if is_hls(streaming_url):
        hls_url = streaming_url
    else:
        # start ffmpeg conversion thread
        if stream_id not in active_streams:
            active_streams[stream_id] = {"source": streaming_url, "time": datetime.now(), "is_played": False, "viewers":0, "last_access": datetime.now()}
            Thread(target=run_ffmpeg_to_hls, args=(streaming_url, stream_id), daemon=True).start()
        hls_url = f"/static/hls/{stream_id}/index.m3u8"

    # HTML player seperti sebelumnya
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Live Stream</title>
        <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
        <style>
            body {{ background:#000; display:flex; align-items:center; justify-content:center; height:100vh; margin:0; }}
            video {{ width:80%; max-width:900px; border-radius:12px; }}
        </style>
    </head>
    <body>
        <video id="video" controls autoplay muted></video>
        <script>
            const video = document.getElementById('video');
            const src = "{hls_url}";
            if(Hls.isSupported()){{
                const hls = new Hls();
                hls.loadSource(src);
                hls.attachMedia(video);
            }} else {{
                video.src = src;
            }}
        </script>
    </body>
    </html>
    """
    return render_template_string(html)