<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>HLS Player</title>
  <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
</head>
<body>
  <h2>Live Stream</h2>
  <video id="video" width="640" controls autoplay></video>

  <script>
    if (Hls.isSupported()) {
      var hls = new Hls();
      hls.loadSource('/static/hls/live/index.m3u8');
      hls.attachMedia(document.getElementById('video'));
    } else if (document.getElementById('video').canPlayType('application/vnd.apple.mpegurl')) {
      document.getElementById('video').src = '/static/hls/live/index.m3u8';
    }
  </script>
</body>
</html>
