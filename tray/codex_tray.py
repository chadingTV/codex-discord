#!/usr/bin/env python3
"""Codex Discord Bot - Linux System Tray App"""

import subprocess
import os
import sys
import threading
import time
import webbrowser

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
PANEL_SCRIPT = os.path.join(BOT_DIR, "tray", "codex_control_panel.py")
import urllib.request
import json
import re

update_available = False
current_version = "unknown"
is_korean = False
cached_release_notes = ""
cached_new_version = ""

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

    subprocess.run(["git", "pull", "origin", "main", "--tags"], cwd=BOT_DIR)
    if stashed:
        subprocess.run(["git", "stash", "pop"], cwd=BOT_DIR, capture_output=True)
    subprocess.run(["npm", "install"], cwd=BOT_DIR)
    subprocess.run(["npm", "rebuild", "better-sqlite3"], cwd=BOT_DIR)
    subprocess.run(["npm", "run", "build"], cwd=BOT_DIR)

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


def start_bot(icon, item):
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


def open_control_panel(icon=None, item=None):
    if not os.path.exists(PANEL_SCRIPT):
        return
    try:
        subprocess.Popen([sys.executable, PANEL_SCRIPT], start_new_session=True)
    except TypeError:
        subprocess.Popen([sys.executable, PANEL_SCRIPT])


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
    control_panel_item = pystray.MenuItem(
        L("Open Control Panel", "컨트롤 패널 열기"),
        open_control_panel,
        default=True,
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
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(L("Setup Required", "설정 필요"), None, enabled=False),
            pystray.Menu.SEPARATOR,
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
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(L("Running", "실행 중"), None, enabled=False),
            pystray.Menu.SEPARATOR,
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
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(L("Stopped", "중지됨"), None, enabled=False),
            pystray.Menu.SEPARATOR,
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


def main():
    global current_version
    load_language()
    current_version = get_version()
    check_for_updates()

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
        # .env 없으면 자동으로 설정 창 열기
        def auto_open_settings():
            time.sleep(1)
            edit_settings(icon, None)
        threading.Thread(target=auto_open_settings, daemon=True).start()
    elif not is_running():
        # .env 있고 봇이 안 돌면 자동 시작
        def auto_start():
            time.sleep(1)
            start_bot(icon, None)
        threading.Thread(target=auto_start, daemon=True).start()

    refresh_thread = threading.Thread(target=refresh_loop, args=(icon,), daemon=True)
    refresh_thread.start()

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
