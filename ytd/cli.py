"""
ytd/cli.py — Entry point for the ytd application (GUI and CLI).
"""

import argparse
import os
import sys


def _attach_console():
    """Attach to parent console on Windows when running from terminal."""
    if sys.platform == "win32":
        try:
            import ctypes
            if ctypes.windll.kernel32.AttachConsole(-1):
                sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
                sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
        except Exception:
            pass


def _get_icon_path() -> str:
    """Return path to the icon across frozen exe, installed, or source modes."""
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(os.path.join(meipass, "assets", "ytd_icon.ico"))
            candidates.append(os.path.join(meipass, "ytd_icon.ico"))
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, "ytd_icon.ico"))
        candidates.append(os.path.join(exe_dir, "assets", "ytd_icon.ico"))
    else:
        candidates.append(os.path.join(os.path.dirname(__file__), "..", "assets", "ytd_icon.ico"))

    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        candidates.append(os.path.join(local_appdata, "Programs", "YTD", "ytd_icon.ico"))

    for c in candidates:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    return ""


def get_default_download_dir() -> str:
    """Return user's standard Downloads folder across Windows, Linux, and macOS."""
    if sys.platform == "win32":
        try:
            import winreg
            sub_key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_key) as key:
                val, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
                expanded = os.path.expandvars(val)
                if os.path.isdir(expanded):
                    return os.path.abspath(expanded)
        except Exception:
            pass

    if sys.platform.startswith("linux"):
        xdg_config = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        user_dirs_file = os.path.join(xdg_config, "user-dirs.dirs")
        if os.path.isfile(user_dirs_file):
            try:
                with open(user_dirs_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("XDG_DOWNLOAD_DIR="):
                            val = line.split("=", 1)[1].strip("\"'")
                            val = val.replace("$HOME", os.path.expanduser("~"))
                            if os.path.isdir(val):
                                return os.path.abspath(val)
            except Exception:
                pass

    try:
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(downloads, exist_ok=True)
        return os.path.abspath(downloads)
    except Exception:
        return os.path.abspath(".")


def main():
    _attach_console()

    parser = argparse.ArgumentParser(
        prog="ytd",
        description="YouTube and multi-site video downloader powered by yt-dlp.",
    )
    parser.add_argument("url", nargs="?", help="Video or playlist URL to download")
    parser.add_argument("--gui", action="store_true", help="Launch the GUI")
    parser.add_argument(
        "-q", "--quality", default="1080",
        choices=["360", "480", "720", "1080", "1440", "2160"],
        help="Maximum video height in pixels (default: 1080)",
    )
    parser.add_argument("-o", "--output", default=None, help="Output directory (default: Downloads folder)")
    parser.add_argument("--playlist", action="store_true", help="Download complete playlist")
    parser.add_argument("-a", "--audio-only", action="store_true", help="Download audio only as MP3")
    from ytd import __version__
    parser.add_argument("--version", action="version", version=f"ytd {__version__}")

    args = parser.parse_args()

    # Create desktop shortcut on first run
    try:
        from ytd.shortcut import ensure_shortcut
        ensure_shortcut(icon_path=_get_icon_path())
    except Exception:
        pass

    # Launch GUI when no URL is provided or --gui is requested
    if args.gui or not args.url:
        from ytd.gui import run_gui
        run_gui()
        return

    url = args.url.strip().strip('"\'<>')
    if not (url.startswith("http://") or url.startswith("https://")):
        if "youtube.com" in url or "youtu.be" in url or "." in url:
            url = "https://" + url
        else:
            print("[ytd] Error: Invalid URL. Must start with http:// or https://", file=sys.stderr)
            sys.exit(1)

    output_dir = os.path.abspath(args.output) if args.output is not None else get_default_download_dir()

    try:
        os.makedirs(output_dir, exist_ok=True)
    except Exception as e:
        print(f"[ytd] Error: Cannot create output directory '{output_dir}': {e}", file=sys.stderr)
        sys.exit(1)

    from yt_dlp import YoutubeDL
    from ytd.ffmpeg_utils import find_ffmpeg, download_ffmpeg_if_missing

    ffmpeg_bin = find_ffmpeg() or download_ffmpeg_if_missing()

    if args.audio_only:
        fmt = "bestaudio/best"
        if ffmpeg_bin:
            postprocessors = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        else:
            postprocessors = []
        merge_fmt = None
    else:
        if ffmpeg_bin:
            fmt = f"bestvideo[height<={args.quality}]+bestaudio/best[height<={args.quality}]/best"
            merge_fmt = "mp4"
        else:
            fmt = f"best[height<={args.quality}][ext=mp4]/best[height<={args.quality}]/best"
            merge_fmt = None
        postprocessors = []

    out_template = os.path.join(output_dir, "%(title)s.%(ext)s")
    ydl_opts = {
        "format": fmt,
        "merge_output_format": merge_fmt,
        "postprocessors": postprocessors,
        "outtmpl": out_template,
        "noplaylist": not args.playlist,
        "windowsfilenames": True,
        "trim_file_name": 160,
        "retries": 10,
        "fragment_retries": 10,
        "file_access_retries": 5,
        "socket_timeout": 30,
        "continuedl": True,
        "geo_bypass": True,
    }
    if ffmpeg_bin:
        ydl_opts["ffmpeg_location"] = os.path.dirname(ffmpeg_bin)

    print(f"[ytd] Downloading: {url}")
    print(f"[ytd] Quality: {'audio-only (MP3)' if args.audio_only else args.quality + 'p'} -> {output_dir}")

    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        print("[ytd] Done.")
    except Exception as exc:
        print(f"[ytd] Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
