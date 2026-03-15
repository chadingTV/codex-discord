#!/usr/bin/env python3
"""Codex Discord Bot - Linux control panel."""

from __future__ import annotations

import atexit
import json
import os
import select
import signal
import subprocess
import sys
import time
import tkinter as tk
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import ttk


BOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BOT_DIR / ".env"
LANG_PREF_FILE = BOT_DIR / ".tray-lang"
AUTOSTART_FILE = Path.home() / ".config" / "autostart" / "codex-discord-tray.desktop"
USAGE_CACHE_PATH = Path.home() / ".codex" / "rate-limits-cache.json"
PANEL_PID_FILE = BOT_DIR / ".panel.pid"
SERVICE_NAME = "codex-discord"
UPDATE_REPO = "https://api.github.com/repos/chadingTV/codex-discord/releases/latest"
USAGE_URL = "https://chatgpt.com/codex/settings/usage"
GITHUB_URL = "https://github.com/chadingTV/codex-discord"
ISSUES_URL = "https://github.com/chadingTV/codex-discord/issues"

BG_DARK = "#2b221f"
BG_PANEL = "#332826"
BG_BUTTON = "#403230"
FG_WHITE = "#f1ece8"
FG_MUTED = "#b7aaa4"
FG_DIM = "#8d817b"
SEP_COLOR = "#4a3c38"
ACCENT_BLUE = "#2f88ff"
BTN_STOP = "#5b2f2a"
BTN_RESTART = "#5a4123"
BTN_SETTINGS = "#263a5d"
BTN_GREEN = "#274a2d"
BAR_BG = "#51423d"

EXAMPLE_VALUES = {
    "your_bot_token_here", "your_server_id_here", "your_user_id_here",
    "/Users/yourname/projects", "/Users/you/projects",
}


is_korean = False
current_version = "unknown"
update_available = False
cached_new_version = ""
usage_data = None
usage_last_fetched = None
last_usage_attempt = 0.0
control_panel = None


def load_language():
    global is_korean
    try:
        if LANG_PREF_FILE.exists():
            is_korean = LANG_PREF_FILE.read_text().strip() == "kr"
    except Exception:
        pass


def set_language(korean: bool):
    global is_korean
    is_korean = korean
    try:
        LANG_PREF_FILE.write_text("kr" if korean else "en")
    except Exception:
        pass
    if control_panel:
        control_panel.refresh_ui()


def L(en: str, kr: str) -> str:
    return kr if is_korean else en


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not ENV_PATH.exists():
        return env
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def is_env_configured() -> bool:
    if not ENV_PATH.exists():
        return False
    env = load_env()
    token = env.get("DISCORD_BOT_TOKEN", "")
    guild = env.get("DISCORD_GUILD_ID", "")
    return bool(token and guild and token not in EXAMPLE_VALUES and guild not in EXAMPLE_VALUES)


def is_running() -> bool:
    return (BOT_DIR / ".bot.lock").exists()


def run_bash(command: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", "-lc", command],
        cwd=str(BOT_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def get_version() -> str:
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            cwd=str(BOT_DIR),
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def check_for_updates() -> None:
    global update_available, cached_new_version
    try:
        subprocess.run(["git", "fetch", "origin", "main", "--tags"], cwd=str(BOT_DIR), capture_output=True)
        local = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(BOT_DIR), capture_output=True, text=True).stdout.strip()
        remote = subprocess.run(["git", "rev-parse", "origin/main"], cwd=str(BOT_DIR), capture_output=True, text=True).stdout.strip()
        update_available = bool(local and remote and local != remote)
        if update_available:
            req = urllib.request.Request(UPDATE_REPO, headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "codex-discord-linux-panel"})
            with urllib.request.urlopen(req, timeout=8) as response:
                payload = json.loads(response.read().decode())
                cached_new_version = payload.get("tag_name", "")
        else:
            cached_new_version = ""
    except Exception:
        update_available = False
        cached_new_version = ""


def open_log():
    log_path = BOT_DIR / "bot.log"
    if log_path.exists():
        subprocess.Popen(["xdg-open", str(log_path)])


def open_folder():
    subprocess.Popen(["xdg-open", str(BOT_DIR)])


def open_settings():
    target = ENV_PATH if ENV_PATH.exists() else (BOT_DIR / ".env.example")
    subprocess.Popen(["xdg-open", str(target)])


def open_usage_page():
    webbrowser.open(USAGE_URL)


def open_github():
    webbrowser.open(GITHUB_URL)


def open_issues():
    webbrowser.open(ISSUES_URL)


def is_autostart_enabled() -> bool:
    return AUTOSTART_FILE.exists()


def toggle_autostart() -> None:
    if AUTOSTART_FILE.exists():
        try:
            AUTOSTART_FILE.unlink()
        except OSError:
            pass
    else:
        AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        tray_script = BOT_DIR / "tray" / "codex_tray.py"
        tray_icon = BOT_DIR / "docs" / "icon-rounded.png"
        AUTOSTART_FILE.write_text(
            f"""[Desktop Entry]
Type=Application
Name=Codex Discord Bot Tray
Comment=Codex Discord Bot system tray manager
Exec=/bin/bash -c 'sleep 3 && python3 {tray_script}'
Icon={tray_icon}
Terminal=false
X-GNOME-Autostart-enabled=true
StartupNotify=false
"""
        )
        subprocess.run(["/bin/bash", str(BOT_DIR / "linux-start.sh"), "--regen-service"], capture_output=True)
        subprocess.run(["loginctl", "enable-linger"], capture_output=True)
    if control_panel:
        control_panel.refresh_ui()


def start_bot_service():
    subprocess.run(["systemctl", "--user", "start", SERVICE_NAME], capture_output=True)
    time.sleep(1.5)


def stop_bot_service():
    subprocess.run(["systemctl", "--user", "stop", SERVICE_NAME], capture_output=True)
    time.sleep(1.0)


def restart_bot_service():
    subprocess.run(["systemctl", "--user", "restart", SERVICE_NAME], capture_output=True)
    time.sleep(1.5)


def usage_cache_payload() -> dict | None:
    try:
        return json.loads(USAGE_CACHE_PATH.read_text())
    except Exception:
        return None


def save_usage_cache(usage: dict) -> None:
    USAGE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fetchedAt": time.time(), "usage": usage}
    USAGE_CACHE_PATH.write_text(json.dumps(payload))


def load_usage_cache() -> None:
    global usage_data, usage_last_fetched
    payload = usage_cache_payload()
    if not payload:
        return
    usage_data = payload.get("usage")
    fetched_at = payload.get("fetchedAt")
    if isinstance(fetched_at, (int, float)):
        usage_last_fetched = float(fetched_at)


def _send_json_line(proc: subprocess.Popen, payload: dict) -> None:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def _read_json_line(proc: subprocess.Popen, timeout: float) -> dict | None:
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


def request_codex_usage() -> dict | None:
    command = """
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" >/dev/null 2>&1
codex app-server
"""
    proc = subprocess.Popen(
        ["/bin/bash", "-lc", command],
        cwd=str(BOT_DIR),
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
                "clientInfo": {"name": "codex-discord-linux-panel", "version": current_version},
                "capabilities": {"experimentalApi": True},
            },
        })
        init_response = _read_json_line(proc, 5)
        if not init_response or init_response.get("id") != 1:
            return None

        _send_json_line(proc, {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "account/rateLimits/read",
            "params": {},
        })
        response = _read_json_line(proc, 5)
        if not response or response.get("id") != 2:
            return None
        result = response.get("result") or {}
        return normalize_usage(result)
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
        except Exception:
            pass


def normalize_usage(result: dict) -> dict | None:
    snapshots = result.get("rateLimitsByLimitId") or {}
    primary_snapshot = snapshots.get("codex") or result.get("rateLimits") or {}
    if not primary_snapshot:
        return None

    return {
        "planType": primary_snapshot.get("planType"),
        "buckets": [{
            "title": None,
            "primary": primary_snapshot.get("primary"),
            "secondary": primary_snapshot.get("secondary"),
        }],
    }


def fetch_usage(force: bool = False) -> bool:
    global usage_data, usage_last_fetched, last_usage_attempt
    now = time.time()
    if not force and now - last_usage_attempt < 60:
        return False
    last_usage_attempt = now
    usage = request_codex_usage()
    if not usage:
        return False
    usage_data = usage
    usage_last_fetched = time.time()
    save_usage_cache(usage)
    return True


def usage_rows() -> list[dict]:
    rows = []
    buckets = (usage_data or {}).get("buckets") or []
    for bucket in buckets:
        title = bucket.get("title")
        if bucket.get("primary"):
            rows.append({
                "bucketTitle": title,
                "window": bucket["primary"],
            })
        if bucket.get("secondary"):
            rows.append({
                "bucketTitle": None,
                "window": bucket["secondary"],
            })
    return rows


def usage_label(window: dict) -> str:
    mins = window.get("windowDurationMins")
    if mins == 300:
        return L("5-hour limit", "5시간 한도")
    if mins == 10080:
        return L("7-day limit", "7일 한도")
    if mins:
        return L(f"{mins}-minute limit", f"{mins}분 한도")
    return L("Usage limit", "사용량 한도")


def usage_percent_left(window: dict) -> int:
    return max(0, min(100, 100 - int(window.get("usedPercent", 0))))


def usage_reset_text(window: dict) -> str:
    ts = window.get("resetsAt")
    if not ts:
        return ""
    dt = time.localtime(int(ts))
    now = time.localtime()
    if (dt.tm_year, dt.tm_yday) == (now.tm_year, now.tm_yday):
        formatted = time.strftime("%p %I:%M", dt).lstrip("0") if not is_korean else time.strftime("%p %I:%M", dt).replace("AM", "오전").replace("PM", "오후").lstrip("0")
        return L(f"Resets {formatted}", f"{formatted} 초기화")
    formatted = time.strftime("%b %-d", dt) if not is_korean else f"{dt.tm_mon}월 {dt.tm_mday}일"
    return L(f"Resets on {formatted}", f"{formatted} 초기화")


def usage_bar_color(percent_left: int) -> str:
    if percent_left <= 10:
        return "#ff5d5d"
    if percent_left <= 30:
        return "#ffb347"
    return ACCENT_BLUE


def fetched_label() -> str:
    if not usage_last_fetched:
        return ""
    ago = int(time.time() - usage_last_fetched)
    if ago < 60:
        return L("Updated just now", "방금 갱신됨")
    if ago < 3600:
        return L(f"Updated {ago // 60}m ago", f"{ago // 60}분 전 갱신")
    return L(f"Updated {ago // 3600}h ago", f"{ago // 3600}시간 전 갱신")


class ControlPanel:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Codex Discord Bot")
        self.root.geometry("460x700")
        self.root.configure(bg=BG_DARK)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        self.style.configure("Panel.TCheckbutton", background=BG_DARK, foreground=FG_WHITE)

        self.icon_image = None
        icon_path = BOT_DIR / "docs" / "icon-rounded.png"
        if icon_path.exists():
            try:
                self.icon_image = tk.PhotoImage(file=str(icon_path))
                self.root.iconphoto(True, self.icon_image)
            except Exception:
                self.icon_image = None

        self.container = tk.Frame(self.root, bg=BG_DARK)
        self.container.pack(fill="both", expand=True, padx=24, pady=20)

        self.root.after(100, self.refresh_ui)
        self.root.after(5000, self.refresh_status_loop)
        self.root.after(60_000, self.refresh_usage_loop)

    def close(self) -> None:
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()

    def refresh_status_loop(self) -> None:
        self.refresh_ui()
        self.root.after(5000, self.refresh_status_loop)

    def refresh_usage_loop(self) -> None:
        fetch_usage(force=False)
        self.refresh_ui()
        self.root.after(60_000, self.refresh_usage_loop)

    def refresh_ui(self) -> None:
        current_running = is_running()
        has_env = is_env_configured()
        for child in self.container.winfo_children():
            child.destroy()

        version = current_version
        ypad = 10

        header = tk.Frame(self.container, bg=BG_DARK)
        header.pack(fill="x")
        if self.icon_image:
            icon_label = tk.Label(header, image=self.icon_image, bg=BG_DARK)
            icon_label.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 14))
        title = tk.Label(header, text="Codex Discord Bot", font=("Helvetica", 20, "bold"), bg=BG_DARK, fg=FG_WHITE)
        title.grid(row=0, column=1, sticky="w")
        subtitle = tk.Label(header, text=version, font=("Helvetica", 11), bg=BG_DARK, fg=FG_MUTED)
        subtitle.grid(row=1, column=1, sticky="w")
        lang = tk.Frame(header, bg=BG_DARK)
        lang.grid(row=0, column=2, rowspan=2, sticky="e")
        self.make_lang_button(lang, "EN", not is_korean, lambda: set_language(False)).pack(side="left")
        tk.Label(lang, text="|", bg=BG_DARK, fg=FG_DIM, padx=6).pack(side="left")
        self.make_lang_button(lang, "KR", is_korean, lambda: set_language(True)).pack(side="left")
        header.grid_columnconfigure(1, weight=1)

        self.separator()

        status_text = L("Setup Required", "설정 필요") if not has_env else (L("Running", "실행 중") if current_running else L("Stopped", "중지됨"))
        status_color = "#ff9f1a" if not has_env else ("#3ddc84" if current_running else "#ff5d5d")
        status_panel = self.round_panel(self.container)
        status_panel.pack(fill="x", pady=(0, ypad))
        dot = tk.Canvas(status_panel, width=22, height=22, bg=BG_PANEL, highlightthickness=0)
        dot.create_oval(2, 2, 20, 20, fill=status_color, outline=status_color)
        dot.pack(side="left", padx=(14, 10), pady=14)
        tk.Label(status_panel, text=status_text, font=("Helvetica", 16, "bold"), bg=BG_PANEL, fg=FG_WHITE).pack(side="left", pady=12)

        if usage_data and usage_rows():
            usage_panel = self.round_panel(self.container)
            usage_panel.pack(fill="x", pady=(0, ypad))
            usage_panel.bind("<Button-1>", lambda _e: open_usage_page())
            if usage_data.get("planType"):
                tk.Label(
                    usage_panel,
                    text=str(usage_data["planType"]).upper(),
                    font=("Helvetica", 10, "bold"),
                    bg=BG_PANEL,
                    fg=FG_MUTED,
                ).pack(anchor="ne", padx=14, pady=(12, 0))
            previous_title = None
            for row in usage_rows():
                title = row["bucketTitle"]
                window = row["window"]
                if title and title != previous_title:
                    tk.Label(usage_panel, text=title, font=("Helvetica", 10, "bold"), bg=BG_PANEL, fg=FG_MUTED).pack(anchor="w", padx=14, pady=(8, 0))
                    previous_title = title
                line = tk.Frame(usage_panel, bg=BG_PANEL)
                line.pack(fill="x", padx=14, pady=(10, 0))
                tk.Label(line, text=usage_label(window), font=("Helvetica", 11, "bold"), bg=BG_PANEL, fg=FG_MUTED).pack(side="left")
                tk.Label(line, text=L(f"{usage_percent_left(window)}% left", f"{usage_percent_left(window)}% 남음"), font=("Helvetica", 11, "bold"), bg=BG_PANEL, fg=usage_bar_color(usage_percent_left(window))).pack(side="right")
                bar = tk.Canvas(usage_panel, height=10, bg=BG_PANEL, highlightthickness=0)
                bar.pack(fill="x", padx=14, pady=(6, 0))
                bar.create_rectangle(0, 0, 380, 10, fill=BAR_BG, outline=BAR_BG)
                fill_width = int(380 * usage_percent_left(window) / 100)
                if fill_width > 0:
                    bar.create_rectangle(0, 0, fill_width, 10, fill=usage_bar_color(usage_percent_left(window)), outline=usage_bar_color(usage_percent_left(window)))
                reset = usage_reset_text(window)
                if reset:
                    tk.Label(usage_panel, text=reset, font=("Helvetica", 9), bg=BG_PANEL, fg=FG_DIM).pack(anchor="w", padx=14, pady=(2, 0))
            fetched = fetched_label()
            if fetched:
                tk.Label(usage_panel, text=fetched, font=("Helvetica", 9), bg=BG_PANEL, fg=FG_DIM).pack(anchor="e", padx=14, pady=(8, 10))
        else:
            usage_button = self.make_button(
                self.container,
                L("Load Usage Info", "사용량 정보 불러오기"),
                BG_BUTTON,
                FG_WHITE,
                lambda: self.manual_usage_refresh(),
                full=True,
            )
            usage_button.pack(fill="x", pady=(0, ypad))

        if has_env:
            button_row = tk.Frame(self.container, bg=BG_DARK)
            button_row.pack(fill="x", pady=(0, ypad))
            if current_running:
                self.make_button(button_row, L("Stop Bot", "봇 중지"), BTN_STOP, "#ff9d9d", lambda: self.run_and_refresh(stop_bot_service)).pack(side="left", fill="x", expand=True)
                tk.Frame(button_row, width=10, bg=BG_DARK).pack(side="left")
                self.make_button(button_row, L("Restart Bot", "봇 재시작"), BTN_RESTART, "#ffc76a", lambda: self.run_and_refresh(restart_bot_service)).pack(side="left", fill="x", expand=True)
            else:
                self.make_button(button_row, L("Start Bot", "봇 시작"), BTN_GREEN, "#b3f4bf", lambda: self.run_and_refresh(start_bot_service), full=True).pack(fill="x", expand=True)

        self.make_button(self.container, L("Settings...", "설정..."), BTN_SETTINGS, "#78b3ff", open_settings, full=True).pack(fill="x", pady=(0, ypad))

        util_row = tk.Frame(self.container, bg=BG_DARK)
        util_row.pack(fill="x", pady=(0, ypad))
        self.make_button(util_row, L("View Log", "로그 보기"), BG_BUTTON, FG_WHITE, open_log).pack(side="left", fill="x", expand=True)
        tk.Frame(util_row, width=10, bg=BG_DARK).pack(side="left")
        self.make_button(util_row, L("Open Folder", "폴더 열기"), BG_BUTTON, FG_WHITE, open_folder).pack(side="left", fill="x", expand=True)

        self.separator()

        autostart_var = tk.BooleanVar(value=is_autostart_enabled())
        chk = ttk.Checkbutton(
            self.container,
            text=L("Launch on System Startup", "시스템 시작 시 자동 실행"),
            variable=autostart_var,
            command=toggle_autostart,
            style="Panel.TCheckbutton",
        )
        chk.pack(anchor="w", pady=(0, ypad))

        update_text = L("Update Available - Click to Update", "업데이트 가능 - 클릭하여 업데이트") if update_available else L("Check for Updates", "업데이트 확인")
        self.make_button(self.container, update_text, BG_BUTTON, FG_WHITE, self.check_updates, full=True).pack(fill="x", pady=(0, ypad))

        self.separator()

        note = tk.Label(
            self.container,
            text=L(
                "Closing this window does not stop the bot.\nThe bot runs in the background. Check the tray icon for status.",
                "이 창을 닫아도 봇은 중지되지 않습니다.\n봇은 백그라운드에서 실행됩니다. 트레이 아이콘에서 상태를 확인하세요.",
            ),
            justify="left",
            font=("Helvetica", 10),
            bg=BG_DARK,
            fg=FG_DIM,
        )
        note.pack(anchor="w", pady=(0, ypad))

        links = tk.Frame(self.container, bg=BG_DARK)
        links.pack(fill="x", pady=(4, 0))
        self.make_link(links, "GitHub: chadingTV/codex-discord", open_github).pack(anchor="center")
        self.make_link(links, L("Bug Report / Feature Request", "버그 신고 / 기능 요청"), open_issues).pack(anchor="center", pady=(8, 0))

    def check_updates(self) -> None:
        check_for_updates()
        self.refresh_ui()

    def manual_usage_refresh(self) -> None:
        fetch_usage(force=True)
        self.refresh_ui()

    def run_and_refresh(self, fn) -> None:
        fn()
        fetch_usage(force=True)
        self.refresh_ui()

    def separator(self) -> None:
        tk.Frame(self.container, bg=SEP_COLOR, height=1).pack(fill="x", pady=(4, 14))

    def round_panel(self, parent) -> tk.Frame:
        frame = tk.Frame(parent, bg=BG_PANEL, bd=0, highlightthickness=0)
        return frame

    def make_button(self, parent, text: str, bg: str, fg: str, command, full: bool = False):
        width = 999 if full else 20
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            relief="flat",
            activebackground=bg,
            activeforeground=fg,
            bd=0,
            cursor="hand2",
            font=("Helvetica", 12, "bold"),
            padx=12,
            pady=12,
            width=width,
        )
        return btn

    def make_lang_button(self, parent, text: str, active: bool, command):
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=ACCENT_BLUE if active else BG_BUTTON,
            fg=FG_WHITE if active else FG_MUTED,
            relief="flat",
            bd=0,
            activebackground=ACCENT_BLUE if active else BG_BUTTON,
            activeforeground=FG_WHITE,
            cursor="hand2",
            font=("Helvetica", 10, "bold" if active else "normal"),
            padx=12,
            pady=6,
        )

    def make_link(self, parent, text: str, command):
        label = tk.Label(
            parent,
            text=text,
            fg="#74b8ff",
            bg=BG_DARK,
            cursor="hand2",
            font=("Helvetica", 12),
        )
        label.bind("<Button-1>", lambda _e: command())
        return label


def ensure_single_panel_instance() -> None:
    my_pid = os.getpid()
    if PANEL_PID_FILE.exists():
        try:
            old_pid = int(PANEL_PID_FILE.read_text().strip())
            if old_pid != my_pid:
                os.kill(old_pid, 0)
                sys.exit(0)
        except Exception:
            pass
    PANEL_PID_FILE.write_text(str(my_pid))

    def cleanup() -> None:
        try:
            if PANEL_PID_FILE.exists() and PANEL_PID_FILE.read_text().strip() == str(my_pid):
                PANEL_PID_FILE.unlink()
        except Exception:
            pass

    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))


def main() -> None:
    global current_version, control_panel
    ensure_single_panel_instance()
    load_language()
    current_version = get_version()
    check_for_updates()
    load_usage_cache()
    fetch_usage(force=False)
    control_panel = ControlPanel()
    control_panel.run()


if __name__ == "__main__":
    main()
