#!/usr/bin/env python3
"""Codex Discord Bot - Linux System Tray App"""

import subprocess
import os
import select
import sys
import threading
import time
import webbrowser

# Force gtk backend for left-click support and better tray stability on Linux.
os.environ.setdefault("PYSTRAY_BACKEND", "gtk")

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    print("Installing required packages: pip3 install pystray Pillow")
    subprocess.run([sys.executable, "-m", "pip", "install", "pystray", "Pillow"], check=True)
    import pystray
    from PIL import Image, ImageDraw

SERVICE_NAME = "codex-discord"
BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BOT_DIR, ".env")
LANG_PREF_FILE = os.path.join(BOT_DIR, ".tray-lang")
import urllib.request
import json
import re

update_available = False
current_version = "unknown"
is_korean = False
cached_release_notes = ""
cached_new_version = ""
usage_data = None
usage_last_fetched = None
last_usage_attempt = 0.0
last_usage_error = ""
_control_panel_window = None

USAGE_URL = "https://chatgpt.com/codex/settings/usage"
USAGE_CACHE_PATH = os.path.join(os.path.expanduser("~"), ".codex", "rate-limits-cache.json")

# Placeholder values from .env.example that should be treated as unconfigured
EXAMPLE_VALUES = {
    "your_bot_token_here", "your_server_id_here", "your_user_id_here",
    "/Users/yourname/projects", "/Users/you/projects",
}

# --- Localization ---

def load_language():
    global is_korean
    try:
        if os.path.exists(LANG_PREF_FILE):
            saved = open(LANG_PREF_FILE).read().strip()
            is_korean = (saved == "kr")
    except Exception:
        pass


def set_language(korean, icon):
    global is_korean
    is_korean = korean
    try:
        with open(LANG_PREF_FILE, "w") as f:
            f.write("kr" if korean else "en")
    except Exception:
        pass
    update_icon(icon)
    icon.menu = create_menu()


def L(en, kr):
    return kr if is_korean else en


# --- Env Configuration Check ---

def _load_env():
    env = {}
    if not os.path.exists(ENV_PATH):
        return env
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def is_env_configured():
    if not os.path.exists(ENV_PATH):
        return False
    env = _load_env()
    token = env.get("DISCORD_BOT_TOKEN", "")
    guild = env.get("DISCORD_GUILD_ID", "")
    if not token or token in EXAMPLE_VALUES:
        return False
    if not guild or guild in EXAMPLE_VALUES:
        return False
    return True


def is_running():
    return os.path.exists(os.path.join(BOT_DIR, ".bot.lock"))


def get_version():
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            capture_output=True, text=True, cwd=BOT_DIR
        )
        ver = result.stdout.strip()
        return ver if ver else "unknown"
    except Exception:
        return "unknown"


def _extract_tag(version):
    """'v1.1.0-3-gabcdef' -> 'v1.1.0'"""
    parts = version.split("-")
    if len(parts) >= 3 and parts[-1].startswith("g"):
        return "-".join(parts[:-2])
    return version


def _parse_version(tag):
    """'v1.1.0' -> [1, 1, 0]"""
    cleaned = tag.lstrip("v")
    try:
        return [int(x) for x in cleaned.split(".")]
    except ValueError:
        return [0]


def _is_newer(a, b):
    """Returns True if version a > b"""
    for i in range(max(len(a), len(b))):
        av = a[i] if i < len(a) else 0
        bv = b[i] if i < len(b) else 0
        if av > bv:
            return True
        if av < bv:
            return False
    return False


def _strip_markdown(text):
    result = text.replace("**", "")
    result = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", result)
    lines = [line for line in result.split("\n") if "Full Changelog:" not in line]
    result = "\n".join(lines)
    while "\n\n\n" in result:
        result = result.replace("\n\n\n", "\n\n")
    return result.strip()


def fetch_release_notes():
    global cached_release_notes, cached_new_version
    try:
        url = "https://api.github.com/repos/chadingTV/codex-discord/releases"
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/vnd.github.v3+json")
        req.add_header("User-Agent", "codex-discord-tray")
        with urllib.request.urlopen(req, timeout=10) as response:
            releases = json.loads(response.read().decode())

        current_tag = _extract_tag(current_version)
        current_parts = _parse_version(current_tag)
        notes = []
        latest_tag = current_tag

        for r in releases:
            tag = r.get("tag_name", "")
            body = r.get("body", "")
            if r.get("draft", False):
                continue
            r_parts = _parse_version(tag)
            if _is_newer(r_parts, current_parts):
                notes.append((tag, body))
                if _is_newer(r_parts, _parse_version(latest_tag)):
                    latest_tag = tag

        notes.sort(key=lambda x: _parse_version(x[0]))
        formatted = "\n\n".join(
            f"━━━ {tag} ━━━\n{_strip_markdown(body)}" for tag, body in notes
        )
        cached_release_notes = formatted
        cached_new_version = latest_tag
    except Exception:
        cached_release_notes = ""
        cached_new_version = ""


def check_for_updates():
    global update_available, current_version
    try:
        current_version = get_version()
        subprocess.run(["git", "fetch", "origin", "main", "--tags"], capture_output=True, cwd=BOT_DIR)
        local = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=BOT_DIR
        ).stdout.strip()
        remote = subprocess.run(
            ["git", "rev-parse", "origin/main"], capture_output=True, text=True, cwd=BOT_DIR
        ).stdout.strip()
        update_available = bool(local and remote and local != remote)
        if update_available:
            fetch_release_notes()
    except Exception:
        update_available = False


def repo_has_local_changes():
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=BOT_DIR,
            capture_output=True,
            text=True,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def _show_update_confirmation():
    """Show update confirmation dialog with release notes using yad or zenity."""
    title = L("Update Available", "업데이트 가능")
    version_info = f"{current_version} → {cached_new_version}" if cached_new_version else ""

    if cached_release_notes:
        text = (version_info + "\n\n" + cached_release_notes) if version_info else cached_release_notes
        # Try yad first
        try:
            result = subprocess.run(
                ["yad", "--text-info", "--title=" + title,
                 "--width=500", "--height=400",
                 "--button=" + L("Update:0", "업데이트:0"),
                 "--button=" + L("Cancel:1", "취소:1"),
                 "--fontname=monospace 10", "--wrap"],
                input=text, text=True, capture_output=True
            )
            return result.returncode == 0
        except FileNotFoundError:
            pass
        # zenity fallback
        try:
            result = subprocess.run(
                ["zenity", "--text-info", "--title=" + title,
                 "--width=500", "--height=400",
                 "--ok-label=" + L("Update", "업데이트"),
                 "--cancel-label=" + L("Cancel", "취소")],
                input=text, text=True, capture_output=True
            )
            return result.returncode == 0
        except FileNotFoundError:
            pass

    # No release notes or no dialog tool — simple question
    msg = L("Do you want to update to the latest version?",
            "최신 버전으로 업데이트하시겠습니까?")
    if version_info:
        msg = version_info + "\n\n" + msg
    try:
        result = subprocess.run(
            ["zenity", "--question", "--title=" + title, "--text=" + msg],
            capture_output=True
        )
        return result.returncode == 0
    except FileNotFoundError:
        pass
    try:
        result = subprocess.run(
            ["yad", "--question", "--title=" + title, "--text=" + msg],
            capture_output=True
        )
        return result.returncode == 0
    except FileNotFoundError:
        pass
    # No dialog tool available — proceed anyway
    return True


def perform_update(icon, item):
    global update_available, current_version
    if not _show_update_confirmation():
        return

    # Stop bot before update
    subprocess.run(["systemctl", "--user", "stop", SERVICE_NAME], capture_output=True)
    time.sleep(1)

    stashed = False
    if repo_has_local_changes():
        subprocess.run(["git", "stash", "push", "-u", "-m", "codex-discord-auto-update"], cwd=BOT_DIR, capture_output=True)
        stashed = True

    subprocess.run(["git", "fetch", "origin", "main", "--tags"], capture_output=True, cwd=BOT_DIR)
    pull_result = subprocess.run(
        ["git", "reset", "--hard", "origin/main"],
        capture_output=True,
        text=True,
        cwd=BOT_DIR,
    )

    if pull_result.returncode != 0:
        err_msg = pull_result.stderr.strip() or pull_result.stdout.strip() or "Unknown error"
        if stashed:
            subprocess.run(["git", "stash", "pop"], cwd=BOT_DIR, capture_output=True)
        icon.notify(L("Update failed (git pull): ", "업데이트 실패 (git pull): ") + err_msg,
                    L("Update Failed", "업데이트 실패"))
        subprocess.run(["systemctl", "--user", "start", SERVICE_NAME], capture_output=True)
        update_icon(icon)
        return

    if stashed:
        subprocess.run(["git", "stash", "pop"], cwd=BOT_DIR, capture_output=True)
    install_result = subprocess.run(["npm", "install"], capture_output=True, text=True, cwd=BOT_DIR)
    subprocess.run(["npm", "rebuild", "better-sqlite3"], capture_output=True, cwd=BOT_DIR)
    build_result = subprocess.run(["npm", "run", "build"], capture_output=True, text=True, cwd=BOT_DIR)

    if install_result.returncode != 0 or build_result.returncode != 0:
        failing_result = install_result if install_result.returncode != 0 else build_result
        failed_step = "install" if install_result.returncode != 0 else "build"
        err_msg = failing_result.stderr.strip() or failing_result.stdout.strip() or "Unknown error"
        icon.notify(
            L(f"Update failed ({failed_step}): ", f"업데이트 실패 ({'설치' if failed_step == 'install' else '빌드'}): ") + err_msg[:200],
            L("Update Failed", "업데이트 실패"),
        )
        subprocess.run(["systemctl", "--user", "start", SERVICE_NAME], capture_output=True)
        update_icon(icon)
        return

    # Regenerate systemd service file (node path may change)
    start_script = os.path.join(BOT_DIR, "linux-start.sh")
    subprocess.run(["/bin/bash", start_script, "--regen-service"], capture_output=True)

    current_version = get_version()
    update_available = False

    # Always restart bot after update
    subprocess.run(["systemctl", "--user", "enable", SERVICE_NAME], capture_output=True)
    subprocess.run(["systemctl", "--user", "start", SERVICE_NAME], capture_output=True)

    time.sleep(2)
    update_icon(icon)
    icon.menu = create_menu()
    icon.notify(L("Updated to version: ", "업데이트 완료: ") + current_version,
                L("Update Complete", "업데이트 완료"))


def create_icon(color):
    """Create a colored circle icon"""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 8
    draw.ellipse([margin, margin, size - margin, size - margin], fill=color)
    return img


def auto_rebuild_if_needed():
    """Auto-rebuild if source is newer than dist."""
    dist_path = os.path.join(BOT_DIR, "dist", "index.js")
    if not os.path.exists(dist_path):
        subprocess.run(["npm", "install"], capture_output=True, cwd=BOT_DIR)
        subprocess.run(["npm", "run", "build"], capture_output=True, cwd=BOT_DIR)
        return

    dist_mtime = os.path.getmtime(dist_path)
    src_dir = os.path.join(BOT_DIR, "src")
    for root, _, files in os.walk(src_dir):
        for f in files:
            if f.endswith(".ts") and os.path.getmtime(os.path.join(root, f)) > dist_mtime:
                subprocess.run(["npm", "install"], capture_output=True, cwd=BOT_DIR)
                subprocess.run(["npm", "run", "build"], capture_output=True, cwd=BOT_DIR)
                return


def start_bot(icon, item):
    auto_rebuild_if_needed()
    subprocess.run(["systemctl", "--user", "start", SERVICE_NAME], capture_output=True)
    time.sleep(2)
    update_icon(icon)
    icon.menu = create_menu()
    if is_running():
        icon.notify(L("Bot is running. Click tray icon to manage.",
                       "봇이 실행 중입니다. 트레이 아이콘을 클릭하여 관리하세요."),
                    L("Codex Discord Bot Started", "Codex Discord Bot 시작됨"))


def stop_bot(icon, item):
    subprocess.run(["systemctl", "--user", "stop", SERVICE_NAME], capture_output=True)
    time.sleep(1)
    update_icon(icon)
    icon.menu = create_menu()


def restart_bot(icon, item):
    subprocess.run(["systemctl", "--user", "restart", SERVICE_NAME], capture_output=True)
    time.sleep(2)
    update_icon(icon)
    icon.menu = create_menu()


def open_log(icon, item):
    log_path = os.path.join(BOT_DIR, "bot.log")
    if os.path.exists(log_path):
        subprocess.Popen(["xdg-open", log_path])


def open_folder(icon, item):
    subprocess.Popen(["xdg-open", BOT_DIR])


def open_github(icon, item):
    webbrowser.open("https://github.com/chadingTV/codex-discord")


def open_github_issues(icon, item):
    webbrowser.open("https://github.com/chadingTV/codex-discord/issues")


def edit_settings(icon, item):
    """Open settings dialog using GTK3 (native look) or fallback"""
    try:
        _edit_settings_gtk(icon)
    except Exception:
        # Fallback: open in text editor
        env_path = os.path.join(BOT_DIR, ".env")
        if os.path.exists(env_path):
            subprocess.Popen(["xdg-open", env_path])
        else:
            subprocess.Popen(["xdg-open", os.path.join(BOT_DIR, ".env.example")])


def _edit_settings_gtk(icon=None):
    """Edit settings using GTK3 native dialog with pre-filled values"""
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    env = _load_env()
    fields = [
        ("DISCORD_BOT_TOKEN", L("Discord Bot Token", "Discord 봇 토큰")),
        ("DISCORD_GUILD_ID", L("Discord Guild ID (Server ID)", "Discord Guild ID (서버 ID)")),
        ("ALLOWED_USER_IDS", L("Allowed User IDs (comma-separated)", "허용된 사용자 ID (쉼표로 구분)")),
        ("BASE_PROJECT_DIR", L("Base Project Directory", "기본 프로젝트 디렉토리")),
        ("RATE_LIMIT_PER_MINUTE", L("Rate Limit Per Minute", "분당 요청 제한")),
        ("SHOW_COST", L("Show Cost (true/false)", "비용 표시 (true/false)")),
    ]
    defaults = {"RATE_LIMIT_PER_MINUTE": "10", "SHOW_COST": "true", "BASE_PROJECT_DIR": ""}
    placeholders = {
        "DISCORD_BOT_TOKEN": L("Paste your bot token here", "봇 토큰을 여기에 붙여넣으세요"),
        "DISCORD_GUILD_ID": L("Right-click server > Copy Server ID", "서버 우클릭 > 서버 ID 복사"),
        "ALLOWED_USER_IDS": L("e.g. 123456789,987654321", "예: 123456789,987654321"),
        "BASE_PROJECT_DIR": L("e.g. /home/you/projects", "예: /home/you/projects"),
        "RATE_LIMIT_PER_MINUTE": "10",
        "SHOW_COST": L("false recommended for Max plan", "Max 요금제는 false 권장"),
    }

    dialog = Gtk.Dialog(
        title=L("Codex Discord Bot Settings", "Codex Discord Bot 설정"),
        flags=0,
    )
    dialog.add_buttons(
        L("Cancel", "취소"), Gtk.ResponseType.CANCEL,
        L("Save", "저장"), Gtk.ResponseType.OK
    )
    dialog.set_default_size(550, -1)
    dialog.set_position(Gtk.WindowPosition.CENTER)
    dialog.set_border_width(15)

    # Style the Save button
    save_btn = dialog.get_widget_for_response(Gtk.ResponseType.OK)
    save_btn.get_style_context().add_class("suggested-action")

    content = dialog.get_content_area()
    content.set_spacing(8)

    # Title
    title = Gtk.Label()
    title.set_markup(f"<b><big>{L('Codex Discord Bot Settings', 'Codex Discord Bot 설정')}</big></b>")
    title.set_halign(Gtk.Align.START)
    content.pack_start(title, False, False, 0)

    subtitle = Gtk.Label(label=L("Please fill in the required fields.", "필수 항목을 입력해주세요."))
    subtitle.set_halign(Gtk.Align.START)
    subtitle.get_style_context().add_class("dim-label")
    content.pack_start(subtitle, False, False, 0)

    # Setup guide link
    link = Gtk.LinkButton.new_with_label(
        "https://github.com/chadingTV/codex-discord/blob/main/SETUP.md",
        L("Open Setup Guide", "설정 가이드 열기")
    )
    link.set_halign(Gtk.Align.START)
    content.pack_start(link, False, False, 0)

    issue_link = Gtk.LinkButton.new_with_label(
        "https://github.com/chadingTV/codex-discord/issues",
        L("Bug Report / Feature Request (GitHub Issues)", "버그 신고 / 기능 요청 (GitHub Issues)")
    )
    issue_link.set_halign(Gtk.Align.START)
    content.pack_start(issue_link, False, False, 0)

    content.pack_start(Gtk.Separator(), False, False, 4)

    entries = {}
    for key, label_text in fields:
        lbl = Gtk.Label()
        lbl.set_markup(f"<b>{label_text}:</b>")
        lbl.set_halign(Gtk.Align.START)
        content.pack_start(lbl, False, False, 0)

        if key == "BASE_PROJECT_DIR":
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            entry = Gtk.Entry()
            entry.set_hexpand(True)
            entry.set_placeholder_text(placeholders.get(key, ""))
            hbox.pack_start(entry, True, True, 0)

            browse_btn = Gtk.Button(label=L("Browse...", "찾아보기..."))
            def on_browse(btn, e=entry):
                chooser = Gtk.FileChooserDialog(
                    title=L("Select Base Project Directory", "기본 프로젝트 디렉토리 선택"),
                    action=Gtk.FileChooserAction.SELECT_FOLDER,
                )
                chooser.add_buttons(
                    L("Cancel", "취소"), Gtk.ResponseType.CANCEL,
                    L("Select", "선택"), Gtk.ResponseType.OK
                )
                chooser.set_position(Gtk.WindowPosition.CENTER)
                if chooser.run() == Gtk.ResponseType.OK:
                    e.set_text(chooser.get_filename())
                chooser.destroy()
            browse_btn.connect("clicked", on_browse)
            hbox.pack_start(browse_btn, False, False, 0)
            content.pack_start(hbox, False, False, 0)
        else:
            entry = Gtk.Entry()
            entry.set_placeholder_text(placeholders.get(key, ""))
            content.pack_start(entry, False, False, 0)

        # Pre-fill (filter out example values)
        current = env.get(key, "")
        if current in EXAMPLE_VALUES:
            current = ""

        if key == "DISCORD_BOT_TOKEN" and len(current) > 10:
            entry.set_placeholder_text(
                "****" + current[-6:] + L(" (enter full token to change)", " (변경하려면 전체 토큰 입력)")
            )
        elif current:
            entry.set_text(current)
        else:
            default = defaults.get(key, "")
            if default:
                entry.set_text(default)

        entries[key] = entry

    note = Gtk.Label(label=L(
        "* Max plan users should set Show Cost to false",
        "* Max 요금제 사용자는 Show Cost를 false로 설정하세요"
    ))
    note.set_halign(Gtk.Align.START)
    note.get_style_context().add_class("dim-label")
    content.pack_start(note, False, False, 4)

    dialog.show_all()
    response = dialog.run()

    if response == Gtk.ResponseType.OK:
        new_env = {}
        for key, _ in fields:
            val = entries[key].get_text().strip()
            if val:
                new_env[key] = val
            elif key == "DISCORD_BOT_TOKEN":
                # Keep existing token if left empty
                existing = env.get(key, "")
                if existing not in EXAMPLE_VALUES:
                    new_env[key] = existing
                else:
                    new_env[key] = ""
            else:
                new_env[key] = defaults.get(key, "")

        if not new_env.get("DISCORD_BOT_TOKEN") or not new_env.get("DISCORD_GUILD_ID") or not new_env.get("ALLOWED_USER_IDS"):
            err = Gtk.MessageDialog(
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text=L(
                    "Bot Token, Guild ID (Server ID), and User IDs are required.",
                    "Bot Token, Guild ID (서버 ID), User IDs는 필수 항목입니다."
                )
            )
            err.run()
            err.destroy()
            dialog.destroy()
            return

        with open(ENV_PATH, "w") as f:
            for key, _ in fields:
                if key == "SHOW_COST":
                    f.write("# Show estimated API cost in task results (set false for Max plan users)\n")
                f.write(f"{key}={new_env.get(key, '')}\n")

    dialog.destroy()

    if icon:
        update_icon(icon)
        icon.menu = create_menu()


AUTOSTART_DIR = os.path.join(os.path.expanduser("~"), ".config", "autostart")
AUTOSTART_FILE = os.path.join(AUTOSTART_DIR, "codex-discord-tray.desktop")


def is_autostart_enabled():
    return os.path.exists(AUTOSTART_FILE)


def toggle_autostart(icon, item):
    if is_autostart_enabled():
        try:
            os.remove(AUTOSTART_FILE)
        except OSError:
            pass
    else:
        os.makedirs(AUTOSTART_DIR, exist_ok=True)
        tray_script = os.path.join(BOT_DIR, "tray", "codex_tray.py")
        tray_icon = os.path.join(BOT_DIR, "docs", "icon-rounded.png")
        with open(AUTOSTART_FILE, "w") as f:
            f.write(f"""[Desktop Entry]
Type=Application
Name=Codex Discord Bot Tray
Comment=Codex Discord Bot system tray manager
Exec=/bin/bash -c 'sleep 3 && python3 {tray_script}'
Icon={tray_icon}
Terminal=false
X-GNOME-Autostart-enabled=true
StartupNotify=false
""")
        # Ensure systemd service file exists for bot management
        start_script = os.path.join(BOT_DIR, "linux-start.sh")
        subprocess.run(["/bin/bash", start_script, "--regen-service"], capture_output=True)
        subprocess.run(["loginctl", "enable-linger"], capture_output=True)
    icon.menu = create_menu()


def _send_json_line(proc, payload):
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def _read_json_line(proc, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = max(0.0, deadline - time.time())
        ready, _, _ = select.select([proc.stdout], [], [], remaining)
        if not ready:
            return None
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                return None
            time.sleep(0.05)
            continue
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def _read_json_response(proc, expected_id, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = _read_json_line(proc, min(0.5, max(0.05, deadline - time.time())))
        if not isinstance(payload, dict):
            continue
        if payload.get("id") == expected_id:
            return payload
    return None


def _read_optional_number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _read_window(value):
    if not isinstance(value, dict):
        return None
    used_percent = _read_optional_number(value.get("usedPercent"))
    if used_percent is None:
        return None
    window = {"usedPercent": used_percent}
    duration = _read_optional_number(value.get("windowDurationMins"))
    resets_at = _read_optional_number(value.get("resetsAt"))
    if duration is not None:
        window["windowDurationMins"] = duration
    if resets_at is not None:
        window["resetsAt"] = resets_at
    return window


def _normalized_buckets(result):
    buckets = []
    for bucket in result.get("buckets") or []:
        if not isinstance(bucket, dict):
            continue
        primary = _read_window(bucket.get("primary"))
        secondary = _read_window(bucket.get("secondary"))
        if not primary and not secondary:
            continue
        buckets.append({
            "title": bucket.get("title") if isinstance(bucket.get("title"), str) else None,
            "primary": primary,
            "secondary": secondary,
        })
    return buckets


def normalize_usage(result):
    buckets = _normalized_buckets(result)
    if buckets:
        usage = {"buckets": buckets}
        plan_type = result.get("planType")
        if isinstance(plan_type, str) and plan_type.strip():
            usage["planType"] = plan_type
        return usage

    snapshots = result.get("rateLimitsByLimitId") or {}
    primary_snapshot = snapshots.get("codex") or result.get("rateLimits") or {}
    if not primary_snapshot:
        return None

    primary = _read_window(primary_snapshot.get("primary"))
    secondary = _read_window(primary_snapshot.get("secondary"))
    if not primary and not secondary:
        return None

    usage = {
        "buckets": [{
            "title": None,
            "primary": primary,
            "secondary": secondary,
        }],
    }
    plan_type = primary_snapshot.get("planType")
    if isinstance(plan_type, str) and plan_type.strip():
        usage["planType"] = plan_type
    return usage


def usage_cache_payload():
    try:
        with open(USAGE_CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def save_usage_cache(usage):
    try:
        os.makedirs(os.path.dirname(USAGE_CACHE_PATH), exist_ok=True)
        with open(USAGE_CACHE_PATH, "w") as f:
            json.dump({"fetchedAt": time.time(), "usage": usage}, f)
    except Exception:
        pass


def load_usage_cache():
    global usage_data, usage_last_fetched
    payload = usage_cache_payload()
    if not isinstance(payload, dict):
        return
    usage = normalize_usage(payload.get("usage") or {})
    if usage:
        usage_data = usage
    fetched_at = payload.get("fetchedAt")
    if isinstance(fetched_at, (int, float)):
        usage_last_fetched = float(fetched_at)


def request_codex_usage():
    global last_usage_error
    command = """
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" >/dev/null 2>&1
codex app-server
"""
    proc = subprocess.Popen(
        ["/bin/bash", "-lc", command],
        cwd=BOT_DIR,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        _send_json_line(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "codex-discord-tray", "version": current_version},
                "capabilities": {"experimentalApi": True},
            },
        })
        init_response = _read_json_response(proc, 1, 5)
        if not init_response or init_response.get("id") != 1:
            last_usage_error = L("Codex app-server did not respond to initialize.", "Codex app-server 초기화 응답이 없습니다.")
            return None

        _send_json_line(proc, {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "account/rateLimits/read",
            "params": {},
        })
        response = _read_json_response(proc, 2, 5)
        if not response or response.get("id") != 2:
            last_usage_error = L("Codex usage request timed out.", "Codex 사용량 요청이 시간 초과되었습니다.")
            return None
        error = response.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                last_usage_error = message.strip()
            else:
                last_usage_error = L("Failed to load Codex usage.", "Codex 사용량을 불러오지 못했습니다.")
            return None
        last_usage_error = ""
        return normalize_usage(response.get("result") or {})
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
        except Exception:
            pass


def fetch_usage(force=False):
    global usage_data, usage_last_fetched, last_usage_attempt, last_usage_error
    now = time.time()
    if not force and now - last_usage_attempt < 60:
        return False
    last_usage_attempt = now
    usage = request_codex_usage()
    if not usage:
        return False
    usage_data = usage
    usage_last_fetched = time.time()
    last_usage_error = ""
    save_usage_cache(usage)
    return True


def usage_rows():
    rows = []
    for bucket in (usage_data or {}).get("buckets") or []:
        title = bucket.get("title")
        if bucket.get("primary"):
            rows.append({"bucketTitle": title, "window": bucket["primary"]})
        if bucket.get("secondary"):
            rows.append({"bucketTitle": None, "window": bucket["secondary"]})
    return rows


def usage_label(window):
    mins = window.get("windowDurationMins")
    if mins == 300:
        return L("5-hour limit", "5시간 한도")
    if mins == 10080:
        return L("7-day limit", "7일 한도")
    if mins:
        return L(f"{mins}-minute limit", f"{mins}분 한도")
    return L("Usage limit", "사용량 한도")


def usage_percent_left(window):
    return max(0, min(100, 100 - int(window.get("usedPercent", 0))))


def usage_reset_text(window):
    ts = window.get("resetsAt")
    if not ts:
        return ""
    dt = time.localtime(int(ts))
    now = time.localtime()
    if (dt.tm_year, dt.tm_yday) == (now.tm_year, now.tm_yday):
        formatted = time.strftime("%p %I:%M", dt)
        if is_korean:
            formatted = formatted.replace("AM", "오전").replace("PM", "오후")
        formatted = formatted.lstrip("0")
        return L(f"Resets {formatted}", f"{formatted} 초기화")

    formatted = time.strftime("%b %d", dt).replace(" 0", " ")
    if is_korean:
        formatted = f"{dt.tm_mon}월 {dt.tm_mday}일"
    return L(f"Resets on {formatted}", f"{formatted} 초기화")


def fetched_label():
    if not usage_last_fetched:
        return ""
    ago = int(time.time() - usage_last_fetched)
    if ago < 60:
        return L("Updated just now", "방금 갱신됨")
    if ago < 3600:
        return L(f"Updated {ago // 60}m ago", f"{ago // 60}분 전 갱신")
    return L(f"Updated {ago // 3600}h ago", f"{ago // 3600}시간 전 갱신")


def show_control_panel(icon, item):
    global _control_panel_window
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib
    except Exception:
        return

    if _control_panel_window is not None:
        try:
            GLib.idle_add(_control_panel_window.present)
            return
        except Exception:
            _control_panel_window = None

    GLib.idle_add(lambda: _show_control_panel_gtk(icon))


def _show_control_panel_gtk(icon):
    global _control_panel_window
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib, Pango

    def rebuild():
        nonlocal content_box
        for child in content_box.get_children():
            content_box.remove(child)

        running = is_running()
        has_env = is_env_configured()

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header.set_margin_start(8)
        header.set_margin_end(8)

        icon_path = os.path.join(BOT_DIR, "docs", "icon-rounded.png")
        if os.path.exists(icon_path):
            try:
                from gi.repository import GdkPixbuf
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(icon_path, 48, 48, True)
                img = Gtk.Image.new_from_pixbuf(pixbuf)
                header.pack_start(img, False, False, 0)
            except Exception:
                pass

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title_label = Gtk.Label()
        title_label.set_markup("<b><big>Codex Discord Bot</big></b>")
        title_label.set_halign(Gtk.Align.START)
        title_box.pack_start(title_label, False, False, 0)
        ver_label = Gtk.Label(label=current_version)
        ver_label.set_halign(Gtk.Align.START)
        ver_label.get_style_context().add_class("dim-label")
        title_box.pack_start(ver_label, False, False, 0)
        header.pack_start(title_box, True, True, 0)

        lang_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        en_btn = Gtk.Button(label="EN")
        kr_btn = Gtk.Button(label="KR")
        en_btn.set_relief(Gtk.ReliefStyle.NONE if is_korean else Gtk.ReliefStyle.NORMAL)
        kr_btn.set_relief(Gtk.ReliefStyle.NORMAL if is_korean else Gtk.ReliefStyle.NONE)

        def on_lang_en(_b):
            set_language(False, icon)
            rebuild()

        def on_lang_kr(_b):
            set_language(True, icon)
            rebuild()

        en_btn.connect("clicked", on_lang_en)
        kr_btn.connect("clicked", on_lang_kr)
        lang_box.pack_start(en_btn, False, False, 0)
        lang_box.pack_start(kr_btn, False, False, 0)
        header.pack_end(lang_box, False, False, 0)

        content_box.pack_start(header, False, False, 0)
        content_box.pack_start(Gtk.Separator(), False, False, 4)

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        status_box.set_margin_start(8)
        dot_color = "orange" if not has_env else ("lime" if running else "red")
        dot_label = Gtk.Label()
        dot_label.set_markup(f'<span foreground="{dot_color}" font="16">●</span>')
        status_box.pack_start(dot_label, False, False, 0)
        status_text = (
            L("Setup Required", "설정 필요") if not has_env
            else (L("Running", "실행 중") if running else L("Stopped", "중지됨"))
        )
        status_label = Gtk.Label()
        status_label.set_markup(f"<b><big>{status_text}</big></b>")
        status_box.pack_start(status_label, False, False, 0)
        content_box.pack_start(status_box, False, False, 4)

        if usage_rows():
            usage_frame = Gtk.Frame()
            usage_frame.set_shadow_type(Gtk.ShadowType.IN)
            usage_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            usage_vbox.set_margin_top(8)
            usage_vbox.set_margin_bottom(8)
            usage_vbox.set_margin_start(10)
            usage_vbox.set_margin_end(10)

            usage_title = Gtk.Label()
            usage_title.set_markup(f"<b>{L('Codex Usage', 'Codex 사용량')}</b>")
            usage_title.set_halign(Gtk.Align.START)
            usage_vbox.pack_start(usage_title, False, False, 0)

            if usage_data and usage_data.get("planType"):
                plan_label = Gtk.Label(label=L("Plan", "플랜") + f": {usage_data['planType']}")
                plan_label.set_halign(Gtk.Align.START)
                plan_label.get_style_context().add_class("dim-label")
                usage_vbox.pack_start(plan_label, False, False, 0)

            previous_title = None
            for row in usage_rows():
                title = row["bucketTitle"]
                window = row["window"]
                if title and title != previous_title:
                    title_label = Gtk.Label()
                    title_label.set_markup(f"<b>{title}</b>")
                    title_label.set_halign(Gtk.Align.START)
                    usage_vbox.pack_start(title_label, False, False, 2)
                    previous_title = title

                line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
                name_lbl = Gtk.Label(label=usage_label(window))
                name_lbl.set_halign(Gtk.Align.START)
                line.pack_start(name_lbl, True, True, 0)
                percent_left = usage_percent_left(window)
                pct_lbl = Gtk.Label()
                color = "red" if percent_left <= 10 else "orange" if percent_left <= 30 else "#4285f4"
                pct_lbl.set_markup(f'<span foreground="{color}"><b>{percent_left}% {L("left", "남음")}</b></span>')
                pct_lbl.set_halign(Gtk.Align.END)
                line.pack_end(pct_lbl, False, False, 0)
                usage_vbox.pack_start(line, False, False, 0)

                pbar = Gtk.ProgressBar()
                pbar.set_fraction(min(max(percent_left / 100.0, 0.0), 1.0))
                pbar.set_size_request(-1, 8)
                pbar.set_show_text(False)
                usage_vbox.pack_start(pbar, False, False, 0)

                reset = usage_reset_text(window)
                if reset:
                    reset_lbl = Gtk.Label(label=reset)
                    reset_lbl.set_halign(Gtk.Align.START)
                    reset_lbl.get_style_context().add_class("dim-label")
                    reset_lbl.modify_font(Pango.FontDescription.from_string("8"))
                    usage_vbox.pack_start(reset_lbl, False, False, 0)

            bottom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            fetched_text = fetched_label()
            if fetched_text:
                fetched_lbl = Gtk.Label(label=fetched_text)
                fetched_lbl.get_style_context().add_class("dim-label")
                fetched_lbl.modify_font(Pango.FontDescription.from_string("8"))
                bottom_row.pack_start(fetched_lbl, True, True, 0)

            refresh_btn = Gtk.Button(label=L("Refresh", "새로고침"))
            refresh_btn.set_relief(Gtk.ReliefStyle.NONE)

            def on_refresh(_b):
                threading.Thread(target=lambda: (fetch_usage(force=True), GLib.idle_add(rebuild)), daemon=True).start()

            refresh_btn.connect("clicked", on_refresh)
            bottom_row.pack_end(refresh_btn, False, False, 0)
            usage_vbox.pack_start(bottom_row, False, False, 2)

            usage_event = Gtk.EventBox()
            usage_event.add(usage_vbox)
            usage_event.connect("button-press-event", lambda _w, _e: webbrowser.open(USAGE_URL))
            usage_event.set_tooltip_text(L("Click to open usage page", "클릭하여 사용량 페이지 열기"))
            usage_frame.add(usage_event)
            content_box.pack_start(usage_frame, False, False, 4)
        else:
            if last_usage_error:
                error_lbl = Gtk.Label(label=L("Usage info unavailable", "사용량 정보를 불러오지 못했습니다."))
                error_lbl.set_halign(Gtk.Align.START)
                error_lbl.get_style_context().add_class("dim-label")
                content_box.pack_start(error_lbl, False, False, 0)

                detail_lbl = Gtk.Label(label=last_usage_error[:180])
                detail_lbl.set_halign(Gtk.Align.START)
                detail_lbl.set_line_wrap(True)
                detail_lbl.get_style_context().add_class("dim-label")
                detail_lbl.modify_font(Pango.FontDescription.from_string("8"))
                content_box.pack_start(detail_lbl, False, False, 0)

            fetch_btn = Gtk.Button(label=L("Load Usage Info", "사용량 정보 불러오기"))

            def on_fetch(_b):
                threading.Thread(target=lambda: (fetch_usage(force=True), GLib.idle_add(rebuild)), daemon=True).start()

            fetch_btn.connect("clicked", on_fetch)
            content_box.pack_start(fetch_btn, False, False, 4)

        content_box.pack_start(Gtk.Separator(), False, False, 4)

        if has_env:
            btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            if running:
                stop_btn = Gtk.Button(label=L("Stop Bot", "봇 중지"))
                stop_btn.get_style_context().add_class("destructive-action")
                stop_btn.connect("clicked", lambda _b: (stop_bot(icon, None), rebuild()))
                btn_box.pack_start(stop_btn, True, True, 0)

                restart_btn = Gtk.Button(label=L("Restart Bot", "봇 재시작"))
                restart_btn.connect("clicked", lambda _b: (restart_bot(icon, None), rebuild()))
                btn_box.pack_start(restart_btn, True, True, 0)
            else:
                start_btn = Gtk.Button(label=L("Start Bot", "봇 시작"))
                start_btn.get_style_context().add_class("suggested-action")
                start_btn.connect("clicked", lambda _b: (start_bot(icon, None), rebuild()))
                btn_box.pack_start(start_btn, True, True, 0)
            content_box.pack_start(btn_box, False, False, 4)

        settings_btn = Gtk.Button(label=L("Settings...", "설정..."))
        settings_btn.connect("clicked", lambda _b: edit_settings(icon, None))
        content_box.pack_start(settings_btn, False, False, 2)

        if has_env:
            util_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            log_btn = Gtk.Button(label=L("View Log", "로그 보기"))
            log_btn.connect("clicked", lambda _b: open_log(icon, None))
            util_box.pack_start(log_btn, True, True, 0)
            folder_btn = Gtk.Button(label=L("Open Folder", "폴더 열기"))
            folder_btn.connect("clicked", lambda _b: open_folder(icon, None))
            util_box.pack_start(folder_btn, True, True, 0)
            content_box.pack_start(util_box, False, False, 2)

        content_box.pack_start(Gtk.Separator(), False, False, 4)

        auto_check = Gtk.CheckButton(label=L("Launch on System Startup", "시스템 시작 시 자동 실행"))
        auto_check.set_active(is_autostart_enabled())
        auto_check.connect("toggled", lambda _b: toggle_autostart(icon, None))
        content_box.pack_start(auto_check, False, False, 2)

        if update_available:
            upd_btn = Gtk.Button(label=L("Update Available - Click to Update", "업데이트 가능 - 클릭하여 업데이트"))
            upd_btn.get_style_context().add_class("suggested-action")
            upd_btn.connect("clicked", lambda _b: (win.destroy(), perform_update(icon, None)))
            content_box.pack_start(upd_btn, False, False, 2)
        else:
            chk_btn = Gtk.Button(label=L("Check for Updates", "업데이트 확인"))

            def on_check_update(_b):
                check_for_updates()
                rebuild()
                if not update_available:
                    dlg = Gtk.MessageDialog(
                        parent=win,
                        message_type=Gtk.MessageType.INFO,
                        buttons=Gtk.ButtonsType.OK,
                        text=L("You are running the latest version.", "최신 버전을 사용 중입니다."),
                    )
                    dlg.run()
                    dlg.destroy()

            chk_btn.connect("clicked", on_check_update)
            content_box.pack_start(chk_btn, False, False, 2)

        content_box.pack_start(Gtk.Separator(), False, False, 4)

        info_label = Gtk.Label(label=L(
            "Closing this window does not stop the bot.\nThe bot runs in the background via systemd.",
            "이 창을 닫아도 봇은 중지되지 않습니다.\n봇은 systemd를 통해 백그라운드에서 실행됩니다."))
        info_label.get_style_context().add_class("dim-label")
        info_label.modify_font(Pango.FontDescription.from_string("8"))
        content_box.pack_start(info_label, False, False, 0)

        quit_btn = Gtk.Button(label=L("Quit", "종료"))
        quit_btn.connect("clicked", lambda _b: (win.destroy(), quit_all(icon, None)))
        content_box.pack_start(quit_btn, False, False, 2)

        content_box.pack_start(Gtk.Separator(), False, False, 4)

        gh_link = Gtk.LinkButton.new_with_label(
            "https://github.com/chadingTV/codex-discord",
            "GitHub: chadingTV/codex-discord")
        content_box.pack_start(gh_link, False, False, 0)
        issue_link = Gtk.LinkButton.new_with_label(
            "https://github.com/chadingTV/codex-discord/issues",
            L("Bug Report / Feature Request (GitHub Issues)", "버그 신고 / 기능 요청 (GitHub Issues)"))
        content_box.pack_start(issue_link, False, False, 0)

        content_box.show_all()

    win = Gtk.Window(title="Codex Discord Bot")
    win.set_default_size(440, -1)
    win.set_position(Gtk.WindowPosition.CENTER)
    win.set_border_width(12)
    win.set_resizable(False)
    win.set_wmclass("codex-discord-bot", "Codex Discord Bot")

    png_path = os.path.join(BOT_DIR, "docs", "icon-rounded.png")
    icon_path = os.path.join(BOT_DIR, "docs", "icon.ico")
    try:
        if os.path.exists(png_path):
            win.set_icon_from_file(png_path)
            Gtk.Window.set_default_icon_from_file(png_path)
        elif os.path.exists(icon_path):
            win.set_icon_from_file(icon_path)
    except Exception:
        pass

    content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    win.add(content_box)
    _control_panel_window = win

    def on_destroy(_w):
        global _control_panel_window
        _control_panel_window = None

    win.connect("destroy", on_destroy)
    rebuild()
    win.show_all()

    def _fetch_if_stale():
        if usage_last_fetched is None or time.time() - usage_last_fetched > 300:
            fetch_usage(force=True)
            GLib.idle_add(rebuild)

    threading.Thread(target=_fetch_if_stale, daemon=True).start()


def quit_all(icon, item):
    if is_running():
        subprocess.run(["systemctl", "--user", "stop", SERVICE_NAME], capture_output=True)
    icon.stop()


def update_icon(icon):
    running = is_running()
    has_env = is_env_configured()
    if not has_env:
        color = (255, 165, 0, 255)  # orange
        icon.title = L("Codex Bot: Setup Required", "Codex Bot: 설정 필요")
    elif running:
        color = (76, 175, 80, 255)  # green
        icon.title = L("Codex Bot: Running", "Codex Bot: 실행 중")
    else:
        color = (244, 67, 54, 255)  # red
        icon.title = L("Codex Bot: Stopped", "Codex Bot: 중지됨")
    icon.icon = create_icon(color)


def manual_check_update(icon, item):
    check_for_updates()
    icon.menu = create_menu()
    if update_available:
        icon.notify(L("A new update is available. Click 'Update' in the menu.",
                       "새 업데이트가 있습니다. 메뉴에서 '업데이트'를 클릭하세요."),
                    L("Update Available", "업데이트 가능"))
    else:
        icon.notify(L("No updates available.", "업데이트가 없습니다."),
                    L("Up to Date", "최신 버전"))


def create_menu():
    running = is_running()
    has_env = is_env_configured()

    # Default item: left-click opens control panel
    control_panel_item = pystray.MenuItem(
        L("Control Panel", "컨트롤 패널"),
        show_control_panel,
        default=True,
        visible=False,
    )

    version_item = pystray.MenuItem(L("Version: ", "버전: ") + current_version, None, enabled=False)
    check_update_item = pystray.MenuItem(
        L("Check for Updates", "업데이트 확인"),
        manual_check_update, visible=not update_available
    )
    update_item = pystray.MenuItem(
        L("Update Available - Click to Update", "업데이트 가능 - 클릭하여 업데이트"),
        perform_update, visible=update_available
    )
    autostart_item = pystray.MenuItem(
        L("Launch on System Startup", "시스템 시작 시 자동 실행"),
        toggle_autostart, checked=lambda item: is_autostart_enabled()
    )

    # Language submenu
    lang_menu = pystray.Menu(
        pystray.MenuItem("English", lambda icon, item: set_language(False, icon),
                         checked=lambda item: not is_korean),
        pystray.MenuItem("한국어", lambda icon, item: set_language(True, icon),
                         checked=lambda item: is_korean),
    )
    lang_item = pystray.MenuItem(
        "Language: KR" if is_korean else "Language: EN",
        lang_menu
    )

    # GitHub link
    github_item = pystray.MenuItem("GitHub: chadingTV/codex-discord", open_github)
    issues_item = pystray.MenuItem(L("Bug Report / Feature Request", "버그 신고 / 기능 요청"), open_github_issues)

    if not has_env:
        return pystray.Menu(
            control_panel_item,
            pystray.MenuItem(L("Setup Required", "설정 필요"), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(L("Control Panel", "컨트롤 패널"), show_control_panel),
            pystray.MenuItem(L("Setup...", "설정..."), edit_settings),
            pystray.Menu.SEPARATOR,
            autostart_item,
            lang_item,
            version_item,
            check_update_item,
            update_item,
            pystray.Menu.SEPARATOR,
            github_item,
            issues_item,
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(L("Quit", "종료"), quit_all),
        )

    if running:
        return pystray.Menu(
            control_panel_item,
            pystray.MenuItem(L("Running", "실행 중"), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(L("Control Panel", "컨트롤 패널"), show_control_panel),
            pystray.MenuItem(L("Stop Bot", "봇 중지"), stop_bot),
            pystray.MenuItem(L("Restart Bot", "봇 재시작"), restart_bot),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(L("Settings...", "설정..."), edit_settings),
            pystray.MenuItem(L("View Log", "로그 보기"), open_log),
            pystray.MenuItem(L("Open Folder", "폴더 열기"), open_folder),
            pystray.Menu.SEPARATOR,
            autostart_item,
            lang_item,
            version_item,
            check_update_item,
            update_item,
            pystray.Menu.SEPARATOR,
            github_item,
            issues_item,
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(L("Quit", "종료"), quit_all),
        )
    else:
        return pystray.Menu(
            control_panel_item,
            pystray.MenuItem(L("Stopped", "중지됨"), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(L("Control Panel", "컨트롤 패널"), show_control_panel),
            pystray.MenuItem(L("Start Bot", "봇 시작"), start_bot),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(L("Settings...", "설정..."), edit_settings),
            pystray.MenuItem(L("View Log", "로그 보기"), open_log),
            pystray.MenuItem(L("Open Folder", "폴더 열기"), open_folder),
            pystray.Menu.SEPARATOR,
            autostart_item,
            lang_item,
            version_item,
            check_update_item,
            update_item,
            pystray.Menu.SEPARATOR,
            github_item,
            issues_item,
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(L("Quit", "종료"), quit_all),
        )


def refresh_loop(icon):
    update_check_counter = 0
    while icon.visible:
        time.sleep(5)
        try:
            update_icon(icon)
            icon.menu = create_menu()
            # Check for git updates every 5 hours (3600 * 5s intervals)
            update_check_counter += 1
            if update_check_counter >= 3600:
                update_check_counter = 0
                check_for_updates()
                icon.menu = create_menu()
        except Exception:
            pass


def _usage_fetch_loop(icon):
    """Fetch usage on start, then every 5 minutes only while panel is open."""
    fetch_usage()
    while icon.visible:
        time.sleep(300)
        try:
            if _control_panel_window is not None:
                fetch_usage()
        except Exception:
            pass


def main():
    global current_version
    load_language()
    current_version = get_version()
    check_for_updates()
    load_usage_cache()

    running = is_running()
    has_env = is_env_configured()
    if not has_env:
        color = (255, 165, 0, 255)  # orange
    elif running:
        color = (76, 175, 80, 255)  # green
    else:
        color = (244, 67, 54, 255)  # red

    icon = pystray.Icon(
        "codex-bot",
        create_icon(color),
        L("Codex Bot", "Codex Bot"),
        menu=create_menu(),
    )

    if not is_env_configured():
        # .env 없으면 패널을 자동으로 열어 설정에 바로 진입할 수 있게 한다.
        def auto_open_settings():
            time.sleep(1)
            show_control_panel(icon, None)
        threading.Thread(target=auto_open_settings, daemon=True).start()
    elif not is_running():
        # .env 있고 봇이 안 돌면 자동 시작
        def auto_start():
            time.sleep(1)
            start_bot(icon, None)
        threading.Thread(target=auto_start, daemon=True).start()

    refresh_thread = threading.Thread(target=refresh_loop, args=(icon,), daemon=True)
    refresh_thread.start()

    usage_thread = threading.Thread(target=_usage_fetch_loop, args=(icon,), daemon=True)
    usage_thread.start()

    icon.run()


def ensure_single_instance():
    """Ensure only one tray app instance is running (PID file based)."""
    pid_file = os.path.join(BOT_DIR, ".tray.pid")
    my_pid = os.getpid()

    # Check if existing instance is alive
    if os.path.exists(pid_file):
        try:
            old_pid = int(open(pid_file).read().strip())
            if old_pid != my_pid:
                os.kill(old_pid, 0)  # Check if process exists
                # Process exists — kill it
                os.kill(old_pid, 9)
                time.sleep(0.5)
        except (ValueError, ProcessLookupError, PermissionError):
            pass  # Process already dead or invalid PID

    # Write our PID
    with open(pid_file, "w") as f:
        f.write(str(my_pid))

    # Cleanup PID file on exit
    import atexit
    atexit.register(lambda: os.remove(pid_file) if os.path.exists(pid_file) else None)


if __name__ == "__main__":
    ensure_single_instance()
    main()
