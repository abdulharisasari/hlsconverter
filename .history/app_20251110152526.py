def start_ffmpeg_to_hls(source_url: str, output_name: str):
    """Loop FFmpeg agar auto-restart kalau stream berhenti"""
    output_path = os.path.join(BASE_HLS_DIR, output_name)
    os.makedirs(output_path, exist_ok=True)

    while output_name in active_streams:
        cmd = [
            "ffmpeg",
            "-y",
            "-i", source_url,
            "-c", "copy",
            "-f", "hls",
            "-hls_time", "4",
            "-hls_list_size", "5",
            "-hls_flags", "delete_segments+append_list+program_date_time",
            os.path.join(output_path, "index.m3u8")
        ]

        print(f"[FFMPEG] Mulai stream ulang untuk {output_name}")
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        process.wait()  # tunggu sampai ffmpeg selesai

        # Kalau sudah dihapus dari active_streams, stop loop
        if output_name not in active_streams:
            print(f"[FFMPEG] Stop {output_name}, sudah dihapus dari active_streams")
            break

        # Kalau masih aktif tapi ffmpeg mati, restart lagi setelah 3 detik
        print(f"[FFMPEG] Restart stream {output_name} dalam 3 detik...")
        time.sleep(3)
