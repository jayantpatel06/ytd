"""
ytd/gui.py — Modern desktop GUI for YouTube Downloader powered by CustomTkinter.
"""

import os
import subprocess
import sys
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk
from yt_dlp import YoutubeDL
from ytd import __version__
from ytd.ffmpeg_utils import find_ffmpeg, download_ffmpeg_if_missing
from ytd.updater import (
    apply_update_and_restart,
    check_for_updates_async,
    download_update_stream,
)


class DownloadCancelledError(Exception):
    """Raised when the user cancels an in-progress download."""
    pass


def open_media(filepath: str):
    """Open a media file with the operating system's default media player."""
    if not filepath or not os.path.exists(filepath):
        messagebox.showerror("File Not Found", "The downloaded media file could not be found.")
        return
    try:
        norm_path = os.path.abspath(os.path.normpath(filepath))
        if sys.platform == "win32":
            os.startfile(norm_path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", norm_path])
        else:
            subprocess.Popen(["xdg-open", norm_path])
    except Exception as exc:
        messagebox.showerror("Playback Error", f"Unable to open media: {exc}")


def open_folder(filepath: str):
    """Open File Explorer with the downloaded file selected."""
    if not filepath or not os.path.exists(filepath):
        messagebox.showerror("File Not Found", "The downloaded media file could not be found.")
        return
    try:
        norm_path = os.path.abspath(os.path.normpath(filepath))
        if sys.platform == "win32":
            subprocess.Popen(["explorer", f"/select,{norm_path}"])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", norm_path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(norm_path)])
    except Exception as exc:
        messagebox.showerror("Error", f"Unable to open destination folder: {exc}")


def _format_display_path(path: str, max_len: int = 40) -> str:
    """Format path for clean UI display with middle truncation if long."""
    if not path:
        return ""
    norm = os.path.abspath(os.path.normpath(path))
    if len(norm) <= max_len:
        return norm
    return norm[:15] + "..." + norm[-(max_len - 18):]


def run_gui():
    # Use native Windows 11 system appearance (Dark or Light automatically)
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.title(f"YouTube Downloader (v{__version__})")
    root.geometry("510x480")
    root.resizable(False, False)

    from ytd.cli import _get_icon_path, get_default_download_dir

    default_dir = get_default_download_dir()
    download_dir = {"path": default_dir}
    is_downloading = {"active": False}
    cancel_requested = {"active": False}
    last_downloaded_file = {"path": ""}

    # Set window icon
    try:
        ico = _get_icon_path()
        if sys.platform == "win32" and ico and os.path.exists(ico):
            root.iconbitmap(ico)
    except Exception:
        pass

    # Thread-safe UI update helpers
    def set_status(text: str):
        root.after(0, lambda: status_label.configure(text=text))

    def set_progress(value: float):
        root.after(0, lambda: progress_bar.set(max(0.0, min(1.0, value / 100.0))))

    def set_action_btn(text: str, state: str = "normal"):
        color = "#dc2626" if text == "Cancel" else ("#0067c0" if text == "Download" else "#64748b")
        hover = "#ef4444" if text == "Cancel" else "#1975c5"
        root.after(0, lambda: action_btn.configure(text=text, state=state, fg_color=color, hover_color=hover))

    def show_play_btn(is_audio: bool = False):
        btn_text = "▶ Play Audio" if is_audio else "▶ Play Video"
        def _show():
            play_btn.configure(text=btn_text)
            completed_frame.pack(after=status_label, pady=(4, 10))
        root.after(0, _show)

    def hide_play_btn():
        root.after(0, lambda: completed_frame.pack_forget())

    def show_error(title: str, message: str):
        root.after(0, lambda: messagebox.showerror(title, message))

    # In-app self-update banner
    def show_update_banner(tag_name: str, download_url: str):
        def _build():
            banner = ctk.CTkFrame(root, height=36, corner_radius=0, fg_color=("#0f172a", "#0f172a"))
            banner.pack(side="bottom", fill="x")

            is_frozen = getattr(sys, "frozen", False)
            text_var = ctk.StringVar(value=f"Update available ({tag_name})")
            lbl = ctk.CTkLabel(
                banner,
                textvariable=text_var,
                text_color="#f1f5f9",
                font=("Segoe UI", 12),
            )
            lbl.pack(side="left", padx=14, pady=4)

            ready_temp_path = {"path": ""}

            def on_update_click():
                if ready_temp_path["path"]:
                    apply_update_and_restart(ready_temp_path["path"])
                    return

                if not is_frozen:
                    import webbrowser
                    webbrowser.open("https://github.com/jayantpatel06/ytd/releases")
                    return

                update_btn.configure(state="disabled")
                text_var.set("Downloading update... 0%")

                def on_progress(pct: float):
                    root.after(0, lambda: text_var.set(f"Downloading update... {pct:.0f}%"))

                def on_complete(temp_path: str):
                    ready_temp_path["path"] = temp_path
                    root.after(0, lambda: text_var.set(f"Version {tag_name} ready."))
                    root.after(
                        0,
                        lambda: update_btn.configure(
                            text="Restart Now",
                            state="normal",
                            fg_color="#10b981",
                            hover_color="#059669",
                        ),
                    )

                def on_err(_err_msg: str):
                    root.after(0, lambda: text_var.set("Update failed."))
                    root.after(0, lambda: update_btn.configure(text="Retry", state="normal"))

                threading.Thread(
                    target=download_update_stream,
                    args=(download_url, on_progress, on_complete, on_err),
                    daemon=True,
                ).start()

            btn_label = "Update" if is_frozen else "View"
            update_btn = ctk.CTkButton(
                banner,
                text=btn_label,
                width=72,
                height=26,
                corner_radius=6,
                font=("Segoe UI", 11, "bold"),
                command=on_update_click,
            )
            update_btn.pack(side="right", padx=14, pady=4)

        root.after(0, _build)

    def on_play_click():
        target = last_downloaded_file.get("path")
        if not target or not os.path.exists(target):
            messagebox.showerror("File Not Found", "The downloaded media file could not be found.")
            return
        open_media(target)

    def on_open_folder_click():
        target = last_downloaded_file.get("path")
        if not target or not os.path.exists(target):
            messagebox.showerror("File Not Found", "The downloaded media file could not be found.")
            return
        open_folder(target)

    def on_paste_click():
        try:
            text = root.clipboard_get()
            if text:
                url_entry.delete(0, "end")
                url_entry.insert(0, text.strip())
        except Exception:
            pass

    def on_action_click():
        if is_downloading["active"]:
            cancel_requested["active"] = True
            set_status("Cancelling download...")
            set_action_btn("Cancelling...", state="disabled")
        else:
            url = url_entry.get().strip().strip('"\'<>')
            if not url:
                messagebox.showerror("Error", "Please enter a valid video or playlist link.")
                return

            # Auto-prepend https:// if omitted
            if not (url.startswith("http://") or url.startswith("https://")):
                if "youtube.com" in url or "youtu.be" in url or "." in url:
                    url = "https://" + url
                else:
                    messagebox.showerror("Error", "URL must start with http:// or https://")
                    return

            out_dir = download_dir["path"] or "."
            try:
                os.makedirs(out_dir, exist_ok=True)
                test_f = os.path.join(out_dir, ".ytd_test_write")
                with open(test_f, "w") as f:
                    f.write("ok")
                os.remove(test_f)
            except Exception as e:
                show_error("Folder Error", f"Cannot write to selected destination folder:\n{e}")
                return

            hide_play_btn()
            last_downloaded_file["path"] = ""
            is_downloading["active"] = True
            cancel_requested["active"] = False
            t = threading.Thread(target=perform_download, args=(url,), daemon=True)
            t.start()

    def perform_download(url: str):
        quality = quality_var.get()
        is_audio = audio_only_var.get()
        out_dir = download_dir["path"] or "."
        out_template = os.path.join(out_dir, "%(title)s.%(ext)s")

        set_progress(0)
        set_status("Starting download...")
        set_action_btn("Cancel")
        hide_play_btn()
        last_downloaded_file["path"] = ""

        downloaded_files = []
        fallback_files = []

        def post_hook(filepath: str):
            if filepath:
                downloaded_files.append(os.path.abspath(filepath))

        def progress_hook(d):
            if cancel_requested["active"]:
                raise DownloadCancelledError()

            if d.get("status") == "downloading":
                raw = str(d.get("_percent_str", "0%")).replace("%", "").strip()
                try:
                    pct = float(raw)
                except ValueError:
                    pct = 0.0
                set_progress(pct)
                speed = d.get("_speed_str", "")
                eta = d.get("_eta_str", "")
                set_status(f"Downloading... {pct:.1f}%  {speed}  ETA {eta}")
            elif d.get("status") == "finished":
                set_status("Extracting audio..." if is_audio else "Merging video and audio...")
                fname = d.get("filename")
                if fname:
                    fallback_files.append(os.path.abspath(fname))

        # Resolve or fetch ffmpeg
        ffmpeg_bin = find_ffmpeg()
        if not ffmpeg_bin:
            set_status("Setting up media engine (first time only)...")
            ffmpeg_bin = download_ffmpeg_if_missing()

        if is_audio:
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
                fmt = f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best"
                merge_fmt = "mp4"
            else:
                # If FFmpeg is unavailable, fall back to pre-merged streams to prevent failure
                fmt = f"best[height<={quality}][ext=mp4]/best[height<={quality}]/best"
                merge_fmt = None
            postprocessors = []

        ydl_opts = {
            "format": fmt,
            "merge_output_format": merge_fmt,
            "postprocessors": postprocessors,
            "progress_hooks": [progress_hook],
            "post_hooks": [post_hook],
            "outtmpl": out_template,
            "noplaylist": not playlist_var.get(),
            "quiet": True,
            "no_warnings": True,
            # Robustness & error avoidance options
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

        try:
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # Resolve the downloaded file path
            chosen_file = None
            candidate_exts = (".mp3", ".m4a", ".mp4") if is_audio else (".mp4", ".mkv", ".webm")
            for p in reversed(downloaded_files):
                if os.path.exists(p):
                    chosen_file = p
                    break
                base, _ = os.path.splitext(p)
                for ext in candidate_exts:
                    if os.path.exists(base + ext):
                        chosen_file = base + ext
                        break
                if chosen_file:
                    break

            if not chosen_file:
                for p in reversed(fallback_files):
                    if os.path.exists(p):
                        chosen_file = p
                        break
                    base, _ = os.path.splitext(p)
                    for ext in candidate_exts:
                        if os.path.exists(base + ext):
                            chosen_file = base + ext
                            break
                    if chosen_file:
                        break

            if chosen_file:
                last_downloaded_file["path"] = chosen_file
                show_play_btn(is_audio=is_audio)

            set_progress(100)
            set_status("Download completed.")
        except DownloadCancelledError:
            set_progress(0)
            set_status("Download cancelled.")
            hide_play_btn()
        except Exception as exc:
            if cancel_requested["active"]:
                set_progress(0)
                set_status("Download cancelled.")
            else:
                err_msg = str(exc)
                if "ERROR:" in err_msg:
                    err_msg = err_msg.split("ERROR:", 1)[1].strip()
                if "Traceback" in err_msg:
                    err_msg = err_msg.split("Traceback", 1)[0].strip()
                show_error("Download Failed", err_msg)
                set_status("Download failed.")
            hide_play_btn()
        finally:
            is_downloading["active"] = False
            cancel_requested["active"] = False
            set_action_btn("Download")

    def choose_directory():
        initial = (
            download_dir["path"]
            if (download_dir["path"] and os.path.isdir(download_dir["path"]))
            else get_default_download_dir()
        )
        path = filedialog.askdirectory(title="Choose download folder", initialdir=initial)
        if path:
            norm_path = os.path.abspath(os.path.normpath(path))
            download_dir["path"] = norm_path
            dir_label.configure(text=_format_display_path(norm_path))

    def on_window_close():
        if is_downloading["active"]:
            cancel_requested["active"] = True
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_window_close)

    # Header / Title
    title_label = ctk.CTkLabel(
        root, text="YouTube Downloader", font=("Segoe UI", 20, "bold")
    )
    title_label.pack(pady=(18, 2))

    subtitle_label = ctk.CTkLabel(
        root,
        text="Fast video & audio downloader powered by yt-dlp",
        font=("Segoe UI", 11),
        text_color=("gray50", "gray70"),
    )
    subtitle_label.pack(pady=(0, 14))

    # URL Input row (with Paste button)
    url_frame = ctk.CTkFrame(root, fg_color="transparent")
    url_frame.pack(pady=4, padx=26, fill="x")

    url_entry = ctk.CTkEntry(
        url_frame,
        placeholder_text="Paste video or playlist link...",
        height=38,
        corner_radius=8,
        font=("Segoe UI", 12),
    )
    url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

    paste_btn = ctk.CTkButton(
        url_frame,
        text="Paste",
        width=70,
        height=38,
        corner_radius=8,
        font=("Segoe UI", 12, "bold"),
        command=on_paste_click,
    )
    paste_btn.pack(side="right")

    # Options row (Quality, Audio Only, Playlist)
    opt_frame = ctk.CTkFrame(root, fg_color="transparent")
    opt_frame.pack(pady=6, padx=26, fill="x")

    q_label = ctk.CTkLabel(opt_frame, text="Quality:", font=("Segoe UI", 12))
    q_label.pack(side="left", padx=(0, 6))

    quality_var = ctk.StringVar(value="1080")
    quality_dd = ctk.CTkComboBox(
        opt_frame,
        variable=quality_var,
        values=["360", "480", "720", "1080", "1440", "2160"],
        width=92,
        height=30,
        corner_radius=6,
        state="readonly",
    )
    quality_dd.pack(side="left", padx=(0, 16))

    def on_audio_only_toggle():
        if audio_only_var.get():
            quality_dd.configure(state="disabled")
        else:
            quality_dd.configure(state="readonly")

    audio_only_var = ctk.BooleanVar(value=False)
    audio_cb = ctk.CTkCheckBox(
        opt_frame,
        text="Audio only (MP3)",
        variable=audio_only_var,
        command=on_audio_only_toggle,
        corner_radius=4,
        font=("Segoe UI", 12),
    )
    audio_cb.pack(side="left", padx=(0, 12))

    playlist_var = ctk.BooleanVar(value=False)
    playlist_cb = ctk.CTkCheckBox(
        opt_frame,
        text="Download playlist",
        variable=playlist_var,
        corner_radius=4,
        font=("Segoe UI", 12),
    )
    playlist_cb.pack(side="left")

    # Destination directory row
    dir_frame = ctk.CTkFrame(root, fg_color="transparent")
    dir_frame.pack(pady=4, padx=26, fill="x")

    browse_btn = ctk.CTkButton(
        dir_frame,
        text="Browse...",
        width=85,
        height=30,
        corner_radius=6,
        font=("Segoe UI", 11),
        command=choose_directory,
    )
    browse_btn.pack(side="left", padx=(0, 10))

    dir_label = ctk.CTkLabel(
        dir_frame,
        text=_format_display_path(download_dir["path"]),
        font=("Segoe UI", 11),
        text_color=("gray50", "gray70"),
    )
    dir_label.pack(side="left")

    # Primary Action Button
    action_btn = ctk.CTkButton(
        root,
        text="Download",
        width=200,
        height=40,
        corner_radius=8,
        font=("Segoe UI", 13, "bold"),
        command=on_action_click,
    )
    action_btn.pack(pady=12)

    # Progress bar and status
    progress_bar = ctk.CTkProgressBar(root, width=448, height=8, corner_radius=4)
    progress_bar.set(0)
    progress_bar.pack(pady=(0, 6))

    status_label = ctk.CTkLabel(
        root, text="Ready", font=("Segoe UI", 12), text_color=("gray40", "gray60")
    )
    status_label.pack(pady=(0, 4))

    # Completed actions (Play & Open Folder)
    completed_frame = ctk.CTkFrame(root, fg_color="transparent")

    play_btn = ctk.CTkButton(
        completed_frame,
        text="▶ Play Video",
        width=140,
        height=36,
        corner_radius=8,
        fg_color="#10b981",
        hover_color="#059669",
        font=("Segoe UI", 12, "bold"),
        command=on_play_click,
    )
    play_btn.pack(side="left", padx=8)

    folder_btn = ctk.CTkButton(
        completed_frame,
        text="📁 Open Folder",
        width=140,
        height=36,
        corner_radius=8,
        fg_color=("gray85", "gray30"),
        hover_color=("gray75", "gray40"),
        text_color=("gray10", "gray95"),
        font=("Segoe UI", 12, "bold"),
        command=on_open_folder_click,
    )
    folder_btn.pack(side="left", padx=8)

    # Background update check (non-blocking)
    threading.Thread(
        target=check_for_updates_async,
        args=(__version__, show_update_banner),
        daemon=True,
    ).start()

    root.mainloop()


if __name__ == "__main__":
    run_gui()
