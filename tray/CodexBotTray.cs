using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

class CodexBotTray : Form
{
    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    private static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, string lParam);
    private const int EM_SETCUEBANNER = 0x1501;

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int attrValue, int attrSize);
    private const int DWMWA_USE_IMMERSIVE_DARK_MODE = 20;

    private NotifyIcon trayIcon;
    private System.Windows.Forms.Timer refreshTimer;
    private System.Windows.Forms.Timer updateCheckTimer;
    private string botDir;
    private string envPath;
    private string taskName = "CodexDiscordBot";
    private string currentVersion = "unknown";
    private bool updateAvailable = false;
    private string cachedReleaseNotes = "";
    private string cachedNewVersion = "";
    private string resolvedCodexCommand = null;
    private Dictionary<string, object> usageData = null;
    private DateTime? usageLastFetched = null;
    private DateTime lastUsageAttempt = DateTime.MinValue;
    private bool lastPanelRunning = false;
    private bool botStarting = false;
    private Color lastIconColor = Color.Empty;
    private IntPtr lastHIcon = IntPtr.Zero;
    private string lastStatusText = "";
    private const string UsageUrl = "https://chatgpt.com/codex/settings/usage";

    // Language support
    private string langPrefFile;
    private bool isKorean = false;

    public CodexBotTray()
    {
        botDir = Path.GetDirectoryName(Path.GetDirectoryName(Application.ExecutablePath));
        envPath = Path.Combine(botDir, ".env");
        langPrefFile = Path.Combine(botDir, ".tray-lang");

        // Load saved language preference
        try
        {
            if (File.Exists(langPrefFile))
            {
                string saved = File.ReadAllText(langPrefFile).Trim();
                isKorean = (saved == "kr");
            }
        }
        catch { }

        this.ShowInTaskbar = false;
        this.WindowState = FormWindowState.Minimized;
        this.FormBorderStyle = FormBorderStyle.None;
        this.Opacity = 0;

        currentVersion = GetVersion();
        LoadUsageCache();

        trayIcon = new NotifyIcon();
        trayIcon.Visible = true;
        // Left-click opens control panel window
        trayIcon.MouseClick += (s, e) => {
            if (e.Button == MouseButtons.Left)
            {
                ShowControlPanel();
            }
        };
        UpdateStatus();
        BuildMenu();

        refreshTimer = new System.Windows.Forms.Timer();
        refreshTimer.Interval = 5000;
        refreshTimer.Tick += (s, e) => { try { if (UpdateStatus()) BuildMenu(); } catch { } };
        refreshTimer.Start();

        // Check for updates every 5 hours
        updateCheckTimer = new System.Windows.Forms.Timer();
        updateCheckTimer.Interval = 18000000;
        updateCheckTimer.Tick += (s, e) => { try { CheckForUpdates(); BuildMenu(); } catch { } };
        updateCheckTimer.Start();

        // Initial update check
        CheckForUpdates();

        bool showPanel = false;
        string[] args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] == "--show") showPanel = true;
        }

        if (!IsEnvConfigured())
        {
            // .env 없거나 설정 안 됐으면 패널 열기 (패널에서 설정 버튼 제공)
            System.Windows.Forms.Timer t = new System.Windows.Forms.Timer();
            t.Interval = 500;
            t.Tick += (s, e) => { t.Stop(); ShowControlPanel(); };
            t.Start();
        }
        else if (!IsRunning())
        {
            // .env 있고 봇이 안 돌고 있으면 자동 시작
            System.Windows.Forms.Timer t = new System.Windows.Forms.Timer();
            t.Interval = 1000;
            t.Tick += (s, e) => { t.Stop(); StartBot(null, null); };
            t.Start();
        }

        if (showPanel)
        {
            System.Windows.Forms.Timer st = new System.Windows.Forms.Timer();
            st.Interval = 1500;
            st.Tick += (s, e) => { st.Stop(); ShowControlPanel(); };
            st.Start();
        }
    }

    // --- Localization ---
    private string L(string en, string kr)
    {
        return isKorean ? kr : en;
    }

    private void SetLanguage(bool korean)
    {
        isKorean = korean;
        try { File.WriteAllText(langPrefFile, korean ? "kr" : "en"); } catch { }
        UpdateStatus();
        BuildMenu();
    }

    private bool IsRunning()
    {
        // 1. Check CodexBot.exe process
        try
        {
            if (Process.GetProcessesByName("CodexBot").Length > 0) return true;
        }
        catch { }
        // 2. Check lock file (written by StartBot cmd chain)
        if (File.Exists(Path.Combine(botDir, ".bot.lock")))
        {
            // Verify lock file is not stale (older than 2 minutes without a matching process)
            try
            {
                var lockAge = DateTime.Now - File.GetLastWriteTime(Path.Combine(botDir, ".bot.lock"));
                if (lockAge.TotalMinutes < 2) return true;
                // Stale lock — check if any node/CodexBot process is actually running
                var proc = new Process();
                proc.StartInfo.FileName = "powershell";
                proc.StartInfo.Arguments = "-NoProfile -Command \"if (Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like '*dist/index.js*' }) { exit 0 } else { exit 1 }\"";
                proc.StartInfo.UseShellExecute = false;
                proc.StartInfo.CreateNoWindow = true;
                proc.Start();
                proc.WaitForExit(5000);
                if (proc.ExitCode == 0) return true;
                // Stale lock file with no process — clean up
                try { File.Delete(Path.Combine(botDir, ".bot.lock")); } catch { }
            }
            catch { return true; } // If we can't check, assume running
        }
        return false;
    }

    private string GetVersion()
    {
        try
        {
            return RunCmdOutput("git", "-C \"" + botDir + "\" describe --tags --always").Trim();
        }
        catch { return "unknown"; }
    }

    private void CheckForUpdates()
    {
        try
        {
            RunCmdOutput("git", "-C \"" + botDir + "\" fetch origin main --tags");
            string local = RunCmdOutput("git", "-C \"" + botDir + "\" rev-parse HEAD").Trim();
            string remote = RunCmdOutput("git", "-C \"" + botDir + "\" rev-parse origin/main").Trim();
            updateAvailable = !string.IsNullOrEmpty(local) && !string.IsNullOrEmpty(remote) && local != remote;
            if (updateAvailable) FetchReleaseNotes();
        }
        catch { updateAvailable = false; }
    }

    private string ExtractTag(string version)
    {
        var parts = version.Split('-');
        if (parts.Length >= 3 && parts[parts.Length - 1].StartsWith("g"))
        {
            var tagParts = new string[parts.Length - 2];
            Array.Copy(parts, tagParts, parts.Length - 2);
            return string.Join("-", tagParts);
        }
        return version;
    }

    private int[] ParseVersion(string tag)
    {
        string cleaned = tag.StartsWith("v") ? tag.Substring(1) : tag;
        var parts = cleaned.Split('.');
        var result = new int[parts.Length];
        for (int i = 0; i < parts.Length; i++)
        {
            int.TryParse(parts[i], out result[i]);
        }
        return result;
    }

    private bool IsNewerVersion(int[] a, int[] b)
    {
        int len = Math.Max(a.Length, b.Length);
        for (int i = 0; i < len; i++)
        {
            int av = i < a.Length ? a[i] : 0;
            int bv = i < b.Length ? b[i] : 0;
            if (av > bv) return true;
            if (av < bv) return false;
        }
        return false;
    }

    private string UsageCachePath()
    {
        return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".codex", "rate-limits-cache.json");
    }

    private string RuntimeCachePath()
    {
        return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".codex", "codex-discord-runtime.json");
    }

    private string ResolveCodexCommand()
    {
        if (!string.IsNullOrWhiteSpace(resolvedCodexCommand) && CommandWorks(resolvedCodexCommand))
            return resolvedCodexCommand;

        try
        {
            string runtimeCache = RuntimeCachePath();
            if (File.Exists(runtimeCache))
            {
                var serializer = new JavaScriptSerializer();
                var payload = serializer.DeserializeObject(File.ReadAllText(runtimeCache)) as Dictionary<string, object>;
                if (payload != null && payload.ContainsKey("codexCommand"))
                {
                    string cachedCommand = payload["codexCommand"] as string;
                    if (!string.IsNullOrWhiteSpace(cachedCommand) && CommandWorks(cachedCommand))
                    {
                        resolvedCodexCommand = cachedCommand;
                        return resolvedCodexCommand;
                    }
                }
            }
        }
        catch { }

        string[] candidates = new string[] { "codex.cmd", "codex.exe", "codex" };
        foreach (string candidate in candidates)
        {
            if (!CommandWorks(candidate)) continue;
            resolvedCodexCommand = candidate;
            SaveRuntimeCache(candidate);
            return resolvedCodexCommand;
        }

        resolvedCodexCommand = "codex.cmd";
        return resolvedCodexCommand;
    }

    private bool CommandWorks(string command)
    {
        try
        {
            var proc = new Process();
            proc.StartInfo.FileName = command;
            proc.StartInfo.Arguments = "--version";
            proc.StartInfo.UseShellExecute = false;
            proc.StartInfo.RedirectStandardOutput = true;
            proc.StartInfo.RedirectStandardError = true;
            proc.StartInfo.CreateNoWindow = true;
            proc.StartInfo.WorkingDirectory = botDir;
            proc.Start();
            if (!proc.WaitForExit(10000))
            {
                try { proc.Kill(); } catch { }
                return false;
            }
            return proc.ExitCode == 0;
        }
        catch
        {
            return false;
        }
    }

    private void SaveRuntimeCache(string codexCommand)
    {
        try
        {
            string runtimeCache = RuntimeCachePath();
            Directory.CreateDirectory(Path.GetDirectoryName(runtimeCache));
            var serializer = new JavaScriptSerializer();
            var payload = new Dictionary<string, object>();
            payload["codexCommand"] = codexCommand;
            File.WriteAllText(runtimeCache, serializer.Serialize(payload));
        }
        catch { }
    }

    private void LoadUsageCache()
    {
        if (usageData != null) return;

        try
        {
            string path = UsageCachePath();
            if (!File.Exists(path)) return;

            var serializer = new JavaScriptSerializer();
            var payload = serializer.DeserializeObject(File.ReadAllText(path)) as Dictionary<string, object>;
            if (payload == null || !payload.ContainsKey("usage")) return;

            var usage = payload["usage"] as Dictionary<string, object>;
            if (usage == null || GetUsageRows(usage).Count == 0) return;

            usageData = usage;
            if (payload.ContainsKey("fetchedAt"))
            {
                double fetchedAt;
                if (TryReadDouble(payload["fetchedAt"], out fetchedAt))
                {
                    if (fetchedAt > 1000000000000d)
                        usageLastFetched = DateTimeOffset.FromUnixTimeMilliseconds((long)fetchedAt).LocalDateTime;
                    else
                        usageLastFetched = DateTimeOffset.FromUnixTimeSeconds((long)fetchedAt).LocalDateTime;
                }
            }
        }
        catch { }
    }

    private void SaveUsageCache(Dictionary<string, object> usage)
    {
        try
        {
            string path = UsageCachePath();
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            var serializer = new JavaScriptSerializer();
            var payload = new Dictionary<string, object>();
            payload["fetchedAt"] = DateTimeOffset.Now.ToUnixTimeMilliseconds();
            payload["usage"] = usage;
            File.WriteAllText(path, serializer.Serialize(payload));
        }
        catch { }
    }

    private bool FetchUsage(bool force)
    {
        try
        {
            if (!force && lastUsageAttempt != DateTime.MinValue && (DateTime.Now - lastUsageAttempt).TotalSeconds < 60)
                return false;

            lastUsageAttempt = DateTime.Now;
            var usage = RequestCodexUsage();
            if (usage == null || GetUsageRows(usage).Count == 0)
                return false;

            usageData = usage;
            usageLastFetched = DateTime.Now;
            SaveUsageCache(usage);
            return true;
        }
        catch
        {
            return false;
        }
    }

    private Dictionary<string, object> RequestCodexUsage()
    {
        string codexCommand = ResolveCodexCommand();
        var proc = new Process();
        proc.StartInfo.FileName = codexCommand;
        proc.StartInfo.Arguments = "app-server";
        proc.StartInfo.UseShellExecute = false;
        proc.StartInfo.RedirectStandardInput = true;
        proc.StartInfo.RedirectStandardOutput = true;
        proc.StartInfo.RedirectStandardError = true;
        proc.StartInfo.CreateNoWindow = true;
        proc.StartInfo.WorkingDirectory = botDir;
        proc.Start();

        try
        {
            SendJsonLine(proc, "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"clientInfo\":{\"name\":\"codex-discord-windows-tray\",\"version\":\"" + EscapeJson(currentVersion) + "\"},\"capabilities\":{\"experimentalApi\":true}}}");
            var initResponse = ReadJsonResponse(proc, 1, 5000);
            if (initResponse == null) return null;

            SendJsonLine(proc, "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"account/rateLimits/read\",\"params\":{}}");
            string response = ReadJsonResponse(proc, 2, 5000);
            if (string.IsNullOrEmpty(response)) return null;

            var serializer = new JavaScriptSerializer();
            var payload = serializer.DeserializeObject(response) as Dictionary<string, object>;
            if (payload == null || !payload.ContainsKey("result")) return null;

            return NormalizeUsage(payload["result"] as Dictionary<string, object>);
        }
        catch
        {
            return null;
        }
        finally
        {
            try { proc.StandardInput.Close(); } catch { }
            try { if (!proc.HasExited) proc.Kill(); } catch { }
            try { proc.Dispose(); } catch { }
        }
    }

    private void SendJsonLine(Process proc, string line)
    {
        proc.StandardInput.WriteLine(line);
        proc.StandardInput.Flush();
    }

    private string ReadJsonLine(Process proc, int timeoutMs)
    {
        DateTime deadline = DateTime.Now.AddMilliseconds(timeoutMs);
        while (DateTime.Now < deadline)
        {
            try
            {
                if (!proc.HasExited && proc.StandardOutput.Peek() >= 0)
                {
                    string line = proc.StandardOutput.ReadLine();
                    if (!string.IsNullOrWhiteSpace(line))
                        return line.Trim();
                }
                else if (proc.HasExited)
                {
                    break;
                }
            }
            catch { break; }
            Thread.Sleep(50);
        }
        return null;
    }

    private string ReadJsonResponse(Process proc, int expectedId, int timeoutMs)
    {
        DateTime deadline = DateTime.Now.AddMilliseconds(timeoutMs);
        while (DateTime.Now < deadline)
        {
            string line = ReadJsonLine(proc, 500);
            if (string.IsNullOrWhiteSpace(line)) continue;
            if (line.Contains("\"id\":" + expectedId) || line.Contains("\"id\": " + expectedId))
                return line;
        }
        return null;
    }

    private Dictionary<string, object> NormalizeUsage(Dictionary<string, object> result)
    {
        if (result == null) return null;

        Dictionary<string, object> primarySnapshot = null;
        if (result.ContainsKey("rateLimitsByLimitId"))
        {
            var snapshots = result["rateLimitsByLimitId"] as Dictionary<string, object>;
            if (snapshots != null && snapshots.ContainsKey("codex"))
            {
                primarySnapshot = snapshots["codex"] as Dictionary<string, object>;
            }
        }

        if (primarySnapshot == null && result.ContainsKey("rateLimits"))
            primarySnapshot = result["rateLimits"] as Dictionary<string, object>;
        if (primarySnapshot == null) return null;

        var primary = ReadWindow(primarySnapshot.ContainsKey("primary") ? primarySnapshot["primary"] : null);
        var secondary = ReadWindow(primarySnapshot.ContainsKey("secondary") ? primarySnapshot["secondary"] : null);
        if (primary == null && secondary == null) return null;

        var bucket = new Dictionary<string, object>();
        bucket["title"] = null;
        if (primary != null) bucket["primary"] = primary;
        if (secondary != null) bucket["secondary"] = secondary;

        var usage = new Dictionary<string, object>();
        if (primarySnapshot.ContainsKey("planType"))
        {
            string planType = primarySnapshot["planType"] as string;
            if (!string.IsNullOrWhiteSpace(planType))
                usage["planType"] = planType;
        }
        usage["buckets"] = new object[] { bucket };
        return usage;
    }

    private Dictionary<string, object> ReadWindow(object value)
    {
        var window = value as Dictionary<string, object>;
        if (window == null) return null;

        double usedPercent;
        if (!TryReadDouble(window.ContainsKey("usedPercent") ? window["usedPercent"] : null, out usedPercent))
            return null;

        var normalized = new Dictionary<string, object>();
        normalized["usedPercent"] = usedPercent;

        double mins;
        if (TryReadDouble(window.ContainsKey("windowDurationMins") ? window["windowDurationMins"] : null, out mins))
            normalized["windowDurationMins"] = mins;

        double resetsAt;
        if (TryReadDouble(window.ContainsKey("resetsAt") ? window["resetsAt"] : null, out resetsAt))
            normalized["resetsAt"] = resetsAt;

        return normalized;
    }

    private bool TryReadDouble(object value, out double number)
    {
        number = 0;
        if (value == null) return false;
        if (value is int) { number = (int)value; return true; }
        if (value is long) { number = (long)value; return true; }
        if (value is float) { number = (float)value; return true; }
        if (value is double) { number = (double)value; return true; }
        if (value is decimal) { number = (double)(decimal)value; return true; }
        return double.TryParse(Convert.ToString(value), out number);
    }

    private string EscapeJson(string text)
    {
        if (string.IsNullOrEmpty(text)) return "";
        return text.Replace("\\", "\\\\").Replace("\"", "\\\"");
    }

    private List<Dictionary<string, object>> GetUsageRows(Dictionary<string, object> usage)
    {
        var rows = new List<Dictionary<string, object>>();
        if (usage == null || !usage.ContainsKey("buckets")) return rows;

        IEnumerable<object> buckets = null;
        if (usage["buckets"] is object[])
            buckets = (object[])usage["buckets"];
        else if (usage["buckets"] is System.Collections.ArrayList)
            buckets = ((System.Collections.ArrayList)usage["buckets"]).ToArray();
        if (buckets == null) return rows;

        foreach (var bucketObj in buckets)
        {
            var bucket = bucketObj as Dictionary<string, object>;
            if (bucket == null) continue;

            object title = bucket.ContainsKey("title") ? bucket["title"] : null;
            var primary = bucket.ContainsKey("primary") ? bucket["primary"] as Dictionary<string, object> : null;
            var secondary = bucket.ContainsKey("secondary") ? bucket["secondary"] as Dictionary<string, object> : null;

            if (primary != null)
            {
                var row = new Dictionary<string, object>();
                row["bucketTitle"] = title;
                row["window"] = primary;
                rows.Add(row);
            }
            if (secondary != null)
            {
                var row = new Dictionary<string, object>();
                row["bucketTitle"] = null;
                row["window"] = secondary;
                rows.Add(row);
            }
        }

        return rows;
    }

    private int UsagePercentLeft(Dictionary<string, object> window)
    {
        double usedPercent;
        if (!TryReadDouble(window.ContainsKey("usedPercent") ? window["usedPercent"] : null, out usedPercent))
            return 0;
        int percentLeft = 100 - (int)Math.Round(usedPercent);
        return Math.Max(0, Math.Min(100, percentLeft));
    }

    private string UsageLabel(Dictionary<string, object> window)
    {
        double mins;
        if (TryReadDouble(window.ContainsKey("windowDurationMins") ? window["windowDurationMins"] : null, out mins))
        {
            if ((int)mins == 300) return L("5-hour limit", "5시간 한도");
            if ((int)mins == 10080) return L("7-day limit", "7일 한도");
            return L(((int)mins) + "-minute limit", ((int)mins) + "분 한도");
        }
        return L("Usage limit", "사용량 한도");
    }

    private string UsageResetText(Dictionary<string, object> window)
    {
        double resetsAt;
        if (!TryReadDouble(window.ContainsKey("resetsAt") ? window["resetsAt"] : null, out resetsAt))
            return "";

        DateTime reset = DateTimeOffset.FromUnixTimeSeconds((long)resetsAt).LocalDateTime;
        DateTime now = DateTime.Now;
        if (reset.Date == now.Date)
        {
            string formatted = reset.ToString("h:mm tt");
            return L("Resets " + formatted, formatted + " 초기화");
        }

        string dateText = reset.ToString("MMM d");
        return L("Resets on " + dateText, dateText + " 초기화");
    }

    private string FetchedLabel()
    {
        if (!usageLastFetched.HasValue) return "";

        TimeSpan ago = DateTime.Now - usageLastFetched.Value;
        if (ago.TotalMinutes < 1)
            return L("Updated just now", "방금 갱신");
        if (ago.TotalHours < 1)
            return L("Updated " + (int)ago.TotalMinutes + "m ago", (int)ago.TotalMinutes + "분 전 갱신");
        return L("Updated " + (int)ago.TotalHours + "h ago", (int)ago.TotalHours + "시간 전 갱신");
    }

    private Color UsageBarColor(int percentLeft)
    {
        if (percentLeft <= 10) return Color.FromArgb(255, 95, 95);
        if (percentLeft <= 30) return Color.FromArgb(255, 186, 73);
        return Color.FromArgb(72, 163, 255);
    }

    private void OpenUsagePage(object sender, EventArgs e)
    {
        try { Process.Start(UsageUrl); } catch { }
    }

    private void RefreshUsageAsync(bool force)
    {
        ThreadPool.QueueUserWorkItem(_ =>
        {
            bool changed = FetchUsage(force);
            if (controlPanel != null && !controlPanel.IsDisposed)
            {
                try
                {
                    controlPanel.BeginInvoke((MethodInvoker)delegate
                    {
                        if (changed || GetUsageRows(usageData).Count == 0)
                            RebuildControlPanel();
                    });
                }
                catch { }
            }
        });
    }

    private void FetchReleaseNotes()
    {
        try
        {
            string currentTag = ExtractTag(currentVersion);
            int[] currentParts = ParseVersion(currentTag);
            // Use PowerShell to call GitHub API and format release notes
            string psScript =
                "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; " +
                "try { " +
                "$r = Invoke-RestMethod -Uri 'https://api.github.com/repos/chadingTV/codex-discord/releases' -TimeoutSec 10 -Headers @{'User-Agent'='codex-discord-tray'}; " +
                "$cv = '" + currentTag.Replace("'", "''") + "'.TrimStart('v').Split('.'); " +
                "$notes = @(); $latest = '" + currentTag.Replace("'", "''") + "'; " +
                "foreach($rel in $r) { " +
                "if($rel.draft) { continue }; " +
                "$rv = $rel.tag_name.TrimStart('v').Split('.'); " +
                "$newer = $false; " +
                "for($i=0; $i -lt [Math]::Max($rv.Length,$cv.Length); $i++) { " +
                "$a = if($i -lt $rv.Length){[int]$rv[$i]}else{0}; " +
                "$b = if($i -lt $cv.Length){[int]$cv[$i]}else{0}; " +
                "if($a -gt $b){$newer=$true;break}; if($a -lt $b){break} }; " +
                "if($newer) { " +
                "$body = $rel.body -replace '\\*\\*','' -replace '\\[([^\\]]+)\\]\\([^)]+\\)','$1'; " +
                "$body = ($body -split \\\"`n\\\" | Where-Object {$_ -notmatch 'Full Changelog:'}) -join \\\"`n\\\"; " +
                "$notes += \\\"--- $($rel.tag_name) ---`n$body\\\"; " +
                "$latest = $rel.tag_name } }; " +
                "Write-Output \\\"LATEST:$latest\\\"; " +
                "Write-Output 'NOTES:'; " +
                "$notes | ForEach-Object { Write-Output $_ } " +
                "} catch { Write-Output 'ERROR' }";
            string output = RunCmdOutput("powershell", "-NoProfile -ExecutionPolicy Bypass -Command \"" + psScript + "\"");
            string latestVersion = "";
            var noteLines = new System.Collections.Generic.List<string>();
            bool inNotes = false;
            foreach (var line in output.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
            {
                if (line.StartsWith("LATEST:")) latestVersion = line.Substring(7);
                else if (line == "NOTES:") inNotes = true;
                else if (inNotes) noteLines.Add(line);
            }
            cachedNewVersion = latestVersion;
            cachedReleaseNotes = string.Join("\r\n", noteLines.ToArray());
        }
        catch
        {
            cachedReleaseNotes = "";
            cachedNewVersion = "";
        }
    }

    private DialogResult ShowUpdateDialog()
    {
        var form = new Form()
        {
            Text = L("Update Available", "업데이트 가능"),
            Width = 500, Height = 450,
            StartPosition = FormStartPosition.CenterScreen,
            FormBorderStyle = FormBorderStyle.FixedDialog,
            MaximizeBox = false, MinimizeBox = false,
            BackColor = Color.FromArgb(30, 30, 30),
            ForeColor = Color.White,
        };
        int val = 1;
        DwmSetWindowAttribute(form.Handle, DWMWA_USE_IMMERSIVE_DARK_MODE, ref val, sizeof(int));

        DialogResult dialogResult = DialogResult.No;

        string versionText = string.IsNullOrEmpty(cachedNewVersion) ? "" : currentVersion + " → " + cachedNewVersion;
        var versionLabel = new Label()
        {
            Text = versionText, Left = 20, Top = 15, Width = 440, Height = 24,
            Font = new Font(FontFamily.GenericSansSerif, 12, FontStyle.Bold),
            ForeColor = Color.White, BackColor = Color.Transparent
        };
        form.Controls.Add(versionLabel);

        var descLabel = new Label()
        {
            Text = L("The bot will restart after updating.", "업데이트 후 봇이 재시작됩니다."),
            Left = 20, Top = 42, Width = 440, Height = 20,
            ForeColor = Color.Gray, BackColor = Color.Transparent,
            Font = new Font(FontFamily.GenericSansSerif, 9)
        };
        form.Controls.Add(descLabel);

        var notesBox = new TextBox()
        {
            Left = 20, Top = 70, Width = 440, Height = 280,
            Multiline = true, ReadOnly = true,
            ScrollBars = ScrollBars.Vertical,
            Text = cachedReleaseNotes,
            BackColor = Color.FromArgb(45, 45, 45), ForeColor = Color.White,
            Font = new Font("Consolas", 9),
            BorderStyle = BorderStyle.None,
        };
        form.Controls.Add(notesBox);

        var updateBtn = new Button()
        {
            Text = L("Update", "업데이트"), Left = 20, Top = 365, Width = 215, Height = 36,
            FlatStyle = FlatStyle.Flat, BackColor = Color.FromArgb(88, 101, 242), ForeColor = Color.White,
            Font = new Font(FontFamily.GenericSansSerif, 10, FontStyle.Bold)
        };
        updateBtn.FlatAppearance.BorderSize = 0;
        updateBtn.Click += (s, ev) => { dialogResult = DialogResult.Yes; form.Close(); };
        form.Controls.Add(updateBtn);

        var cancelBtn = new Button()
        {
            Text = L("Cancel", "취소"), Left = 245, Top = 365, Width = 215, Height = 36,
            FlatStyle = FlatStyle.Flat, BackColor = Color.FromArgb(55, 55, 55), ForeColor = Color.White,
            Font = new Font(FontFamily.GenericSansSerif, 10)
        };
        cancelBtn.FlatAppearance.BorderSize = 0;
        cancelBtn.Click += (s, ev) => { form.Close(); };
        form.Controls.Add(cancelBtn);

        form.ShowDialog();
        form.Dispose();
        return dialogResult;
    }

    private void PerformUpdate(object sender, EventArgs e)
    {
        DialogResult result;
        if (!string.IsNullOrEmpty(cachedReleaseNotes))
        {
            result = ShowUpdateDialog();
        }
        else
        {
            result = MessageBox.Show(
                L("Do you want to update to the latest version? The bot will restart after updating.",
                  "최신 버전으로 업데이트하시겠습니까? 업데이트 후 봇이 재시작됩니다."),
                L("Update Available", "업데이트 가능"),
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Question);
        }

        if (result != DialogResult.Yes) return;

        bool wasRunning = IsRunning();
        if (wasRunning)
        {
            KillBot();
            Thread.Sleep(2000);
        }

        bool hasLocalChanges = !string.IsNullOrWhiteSpace(
            RunCmdOutput("git", "-C \"" + botDir + "\" status --porcelain"));
        if (hasLocalChanges)
        {
            RunCmdOutput("git", "-C \"" + botDir + "\" stash push -u -m \"codex-discord-auto-update\"");
        }

        RunCmdOutput("git", "-C \"" + botDir + "\" pull origin main --tags");
        if (hasLocalChanges)
        {
            RunCmdOutput("git", "-C \"" + botDir + "\" stash pop");
        }
        RunCmd("cd /d \"" + botDir + "\" && npm install && npm rebuild better-sqlite3 && npm run build", true);

        currentVersion = GetVersion();
        updateAvailable = false;

        // Tray exe 재컴파일 및 재시작
        // 실행 중인 자기 자신은 삭제 불가하므로 bat 스크립트로 대기 후 교체
        string trayExe = Application.ExecutablePath;
        string traySrc = Path.Combine(Path.GetDirectoryName(trayExe), "CodexBotTray.cs");
        string updateBat = Path.Combine(botDir, ".tray-update.bat");

        if (File.Exists(traySrc))
        {
            string updateLog = Path.Combine(botDir, "update.log");
            string batContent =
                "@echo off\r\n" +
                "setlocal enabledelayedexpansion\r\n" +
                "set \"LOG=" + updateLog + "\"\r\n" +
                "echo [%date% %time%] Update started > \"%LOG%\"\r\n" +
                ":: Kill all tray processes and wait\r\n" +
                "taskkill /f /im CodexBotTray.exe >nul 2>&1\r\n" +
                "timeout /t 3 /nobreak >nul\r\n" +
                ":: Delete old exe\r\n" +
                "del \"" + trayExe + "\" >nul 2>&1\r\n" +
                "set \"CSC=\"\r\n" +
                "for /f \"delims=\" %%i in ('dir /b /s \"%WINDIR%\\Microsoft.NET\\Framework64\\csc.exe\" 2^>nul') do set \"CSC=%%i\"\r\n" +
                "if \"!CSC!\"==\"\" (\r\n" +
                "    for /f \"delims=\" %%i in ('dir /b /s \"%WINDIR%\\Microsoft.NET\\Framework\\csc.exe\" 2^>nul') do set \"CSC=%%i\"\r\n" +
                ")\r\n" +
                "if \"!CSC!\"==\"\" (\r\n" +
                "    echo [%date% %time%] ERROR: csc.exe not found >> \"%LOG%\"\r\n" +
                "    goto :done\r\n" +
                ")\r\n" +
                "echo [%date% %time%] Compiling with !CSC! >> \"%LOG%\"\r\n" +
                "\"!CSC!\" /nologo /target:winexe /out:\"" + trayExe + "\" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll \"" + traySrc + "\" >> \"%LOG%\" 2>&1\r\n" +
                "if exist \"" + trayExe + "\" (\r\n" +
                "    echo [%date% %time%] Compile OK, restarting >> \"%LOG%\"\r\n" +
                "    start \"\" \"" + trayExe + "\" --show\r\n" +
                ") else (\r\n" +
                "    echo [%date% %time%] ERROR: Compile failed >> \"%LOG%\"\r\n" +
                ")\r\n" +
                ":done\r\n" +
                "del \"" + updateBat + "\" >nul 2>&1\r\n";

            File.WriteAllText(updateBat, batContent);

            var psi = new ProcessStartInfo("cmd.exe", "/c \"" + updateBat + "\"")
            {
                WindowStyle = ProcessWindowStyle.Hidden,
                CreateNoWindow = true,
                UseShellExecute = false,
            };
            Process.Start(psi);

            // 자기 자신 종료 (bat이 대기 후 처리)
            trayIcon.Visible = false;
            Application.Exit();
            return;
        }

        // traySrc 없으면 (비정상 상황) 그냥 봇만 재시작
        if (wasRunning)
        {
            StartBot(null, null);
        }

        MessageBox.Show(L("Updated to version: ", "업데이트 완료: ") + currentVersion,
            L("Update Complete", "업데이트 완료"), MessageBoxButtons.OK, MessageBoxIcon.Information);
        UpdateStatus();
        BuildMenu();
    }

    private string RunCmdOutput(string fileName, string arguments)
    {
        try
        {
            var proc = new Process();
            proc.StartInfo.FileName = fileName;
            proc.StartInfo.Arguments = arguments;
            proc.StartInfo.UseShellExecute = false;
            proc.StartInfo.RedirectStandardOutput = true;
            proc.StartInfo.CreateNoWindow = true;
            proc.StartInfo.WorkingDirectory = botDir;
            proc.Start();
            string output = proc.StandardOutput.ReadToEnd();
            proc.WaitForExit();
            return output;
        }
        catch { return ""; }
    }

    private Bitmap CreateIcon(Color color)
    {
        var bmp = new Bitmap(16, 16);
        using (var g = Graphics.FromImage(bmp))
        using (var brush = new SolidBrush(color))
        {
            g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
            g.FillEllipse(brush, 1, 1, 14, 14);
        }
        return bmp;
    }

    private bool IsEnvConfigured()
    {
        if (!File.Exists(envPath)) return false;
        var env = LoadEnv();
        string token = ""; env.TryGetValue("DISCORD_BOT_TOKEN", out token);
        if (token == null || token == "" || token == "your_bot_token_here") return false;
        string guild = ""; env.TryGetValue("DISCORD_GUILD_ID", out guild);
        if (guild == null || guild == "" || guild == "your_server_id_here") return false;
        return true;
    }

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern bool DestroyIcon(IntPtr handle);

    private void SetTrayIcon(Color color)
    {
        // Skip if color hasn't changed — avoid GDI+ handle accumulation
        if (color == lastIconColor) return;
        lastIconColor = color;

        var bmp = CreateIcon(color);
        IntPtr newHIcon = bmp.GetHicon();
        bmp.Dispose();

        // Destroy previous native icon handle to prevent GDI+ leak
        IntPtr oldHIcon = lastHIcon;
        var oldIcon = trayIcon.Icon;

        trayIcon.Icon = Icon.FromHandle(newHIcon);
        lastHIcon = newHIcon;

        // Dispose managed Icon wrapper, then destroy old native handle
        if (oldIcon != null) { try { oldIcon.Dispose(); } catch { } }
        if (oldHIcon != IntPtr.Zero) { try { DestroyIcon(oldHIcon); } catch { } }
    }

    /// <summary>
    /// Updates tray icon and tooltip. Returns true if status actually changed.
    /// </summary>
    private bool UpdateStatus()
    {
        bool running = IsRunning();
        bool hasEnv = IsEnvConfigured();

        Color color;
        string text;
        if (!hasEnv)
        {
            color = Color.Orange;
            text = L("Codex Discord Bot: Setup Required", "Codex Discord Bot: 설정 필요");
        }
        else if (running)
        {
            color = Color.LimeGreen;
            text = L("Codex Discord Bot: Running", "Codex Discord Bot: 실행 중");
        }
        else
        {
            color = Color.Red;
            text = L("Codex Discord Bot: Stopped", "Codex Discord Bot: 중지됨");
        }

        bool changed = (text != lastStatusText);
        SetTrayIcon(color);
        trayIcon.Text = text;
        lastStatusText = text;
        return changed;
    }

    private void BuildMenu()
    {
        bool running = IsRunning();
        bool hasEnv = IsEnvConfigured();

        var oldMenu = trayIcon.ContextMenuStrip;
        var menu = new ContextMenuStrip();

        if (!hasEnv)
        {
            var noEnv = new ToolStripMenuItem(L("Setup Required", "설정 필요")) { Enabled = false };
            menu.Items.Add(noEnv);
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(L("Setup...", "설정..."), null, OpenSettings);
        }
        else
        {
            var status = new ToolStripMenuItem(running ? L("Running", "실행 중") : L("Stopped", "중지됨")) { Enabled = false };
            menu.Items.Add(status);
            menu.Items.Add(new ToolStripSeparator());

            if (running)
            {
                menu.Items.Add(L("Stop Bot", "봇 중지"), null, StopBot);
                menu.Items.Add(L("Restart Bot", "봇 재시작"), null, RestartBot);
            }
            else
            {
                menu.Items.Add(L("Start Bot", "봇 시작"), null, StartBot);
            }

            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(L("Settings...", "설정..."), null, OpenSettings);
            menu.Items.Add(L("View Log", "로그 보기"), null, OpenLog);
            menu.Items.Add(L("Open Folder", "폴더 열기"), null, OpenFolder);
        }

        menu.Items.Add(new ToolStripSeparator());

        // Auto-start toggle
        var autoStartItem = new ToolStripMenuItem(L("Auto Run on Startup", "시작 시 자동 실행"));
        autoStartItem.Checked = IsAutoStartEnabled();
        autoStartItem.Click += ToggleAutoStart;
        menu.Items.Add(autoStartItem);

        // Language toggle in menu
        var langItem = new ToolStripMenuItem(isKorean ? "Language: KR" : "Language: EN");
        var enItem = new ToolStripMenuItem("English") { Checked = !isKorean };
        enItem.Click += (s, ev) => { SetLanguage(false); };
        var krItem = new ToolStripMenuItem("한국어") { Checked = isKorean };
        krItem.Click += (s, ev) => { SetLanguage(true); };
        langItem.DropDownItems.Add(enItem);
        langItem.DropDownItems.Add(krItem);
        menu.Items.Add(langItem);

        var versionItem = new ToolStripMenuItem(L("Version: ", "버전: ") + currentVersion) { Enabled = false };
        menu.Items.Add(versionItem);

        if (updateAvailable)
        {
            menu.Items.Add(L("Update Available", "업데이트 가능"), null, PerformUpdate);
        }
        else
        {
            menu.Items.Add(L("Check for Updates", "업데이트 확인"), null, (s, ev) => {
                CheckForUpdates();
                if (updateAvailable)
                {
                    BuildMenu();
                }
                else
                {
                    MessageBox.Show(
                        L("You are running the latest version.", "최신 버전을 사용 중입니다."),
                        L("No Updates", "업데이트 없음"),
                        MessageBoxButtons.OK, MessageBoxIcon.Information);
                }
            });
        }

        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(L("Quit", "종료"), null, QuitAll);

        trayIcon.ContextMenuStrip = menu;
        if (oldMenu != null)
        {
            try
            {
                foreach (ToolStripItem item in oldMenu.Items) { try { item.Dispose(); } catch { } }
                oldMenu.Dispose();
            }
            catch { }
        }
    }

    private void StartBot(object sender, EventArgs e)
    {
        botStarting = true;
        RebuildControlPanel();
        KillBot();
        // Copy node.exe as CodexBot.exe so it shows as "CodexBot" in Task Manager
        string codexBotExe = Path.Combine(botDir, "CodexBot.exe");
        try
        {
            string whereOut = RunCmdOutput("where", "node").Trim();
            string nodeExe = whereOut.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)[0].Trim();
            if (File.Exists(nodeExe))
            {
                if (!File.Exists(codexBotExe) ||
                    File.GetLastWriteTime(nodeExe) > File.GetLastWriteTime(codexBotExe))
                {
                    File.Copy(nodeExe, codexBotExe, true);
                }
            }
        }
        catch { }
        // Use absolute path to CodexBot.exe so cmd can find it
        string botExePath = File.Exists(codexBotExe) ? "\"" + codexBotExe + "\"" : "node";
        // Run bot hidden via vbs
        string vbs = Path.Combine(botDir, ".bot-start.vbs");
        string cmd = "cmd /c cd /d " + botDir + " & echo running> .bot.lock & " + botExePath + " dist/index.js >> bot.log 2>&1 & del .bot.lock";
        File.WriteAllText(vbs, "Set ws = CreateObject(\"WScript.Shell\")\nws.Run \"" + cmd.Replace("\"", "\"\"") + "\", 0, False\n");
        Process.Start("wscript", "\"" + vbs + "\"");
        // Wait for bot to start, then show notification
        System.Windows.Forms.Timer waitTimer = new System.Windows.Forms.Timer();
        waitTimer.Interval = 1000;
        int waitCount = 0;
        waitTimer.Tick += (s2, e2) => {
            waitCount++;
            bool nowRunning = IsRunning();
            if (nowRunning)
            {
                waitTimer.Stop();
                botStarting = false;
                try { File.Delete(vbs); } catch { }
                UpdateStatus();
                BuildMenu();
                RebuildControlPanel();
                trayIcon.BalloonTipTitle = L("Codex Discord Bot Started", "Codex Discord Bot 시작됨");
                trayIcon.BalloonTipText = L("Bot is running. Click tray icon to manage.",
                                             "봇이 실행 중입니다. 트레이 아이콘을 클릭하여 관리하세요.");
                trayIcon.BalloonTipIcon = ToolTipIcon.Info;
                trayIcon.ShowBalloonTip(3000);
                trayIcon.BalloonTipClicked += (s3, e3) => { ShowControlPanel(); };
            }
            else if (waitCount > 10)
            {
                waitTimer.Stop();
                botStarting = false;
                try { File.Delete(vbs); } catch { }
                UpdateStatus();
                BuildMenu();
                RebuildControlPanel();
            }
        };
        waitTimer.Start();
    }

    private void KillBot()
    {
        // Kill CodexBot.exe process (copied from node.exe with custom name)
        try
        {
            foreach (var proc in Process.GetProcessesByName("CodexBot"))
            {
                try { proc.Kill(); proc.WaitForExit(3000); } catch { }
            }
        }
        catch { }
        // Fallback: kill any node.exe running dist/index.js (in case CodexBot.exe wasn't used)
        try
        {
            var proc = new Process();
            proc.StartInfo.FileName = "powershell";
            proc.StartInfo.Arguments = "-NoProfile -Command \"Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like '*dist/index.js*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }\"";
            proc.StartInfo.UseShellExecute = false;
            proc.StartInfo.CreateNoWindow = true;
            proc.Start();
            proc.WaitForExit(10000);
        }
        catch { }
        string lockFile = Path.Combine(botDir, ".bot.lock");
        try { File.Delete(lockFile); } catch { }
    }

    private bool IsAutoStartEnabled()
    {
        try
        {
            var key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(
                "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run", false);
            if (key == null) return false;
            object val = key.GetValue(taskName);
            key.Close();
            return val != null;
        }
        catch { return false; }
    }

    private void ToggleAutoStart(object sender, EventArgs e)
    {
        try
        {
            var key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(
                "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run", true);
            if (key == null) return;
            if (IsAutoStartEnabled())
            {
                key.DeleteValue(taskName, false);
            }
            else
            {
                key.SetValue(taskName, "\"" + Application.ExecutablePath + "\"");
            }
            key.Close();
        }
        catch { }
        BuildMenu();
    }

    private void StopBot(object sender, EventArgs e)
    {
        KillBot();
        Thread.Sleep(1000);
        UpdateStatus();
        BuildMenu();
    }

    private void RestartBot(object sender, EventArgs e)
    {
        KillBot();
        Thread.Sleep(2000);
        StartBot(null, null);
    }

    private void OpenLog(object sender, EventArgs e)
    {
        string logPath = Path.Combine(botDir, "bot.log");
        if (!File.Exists(logPath))
            File.Create(logPath).Close();
        Process.Start("notepad.exe", "\"" + logPath + "\"");
    }

    private void OpenFolder(object sender, EventArgs e)
    {
        Process.Start("explorer.exe", botDir);
    }

    private void OpenSettings(object sender, EventArgs e)
    {
        var env = LoadEnv();

        var form = new Form()
        {
            Text = L("Codex Discord Bot Settings", "Codex Discord Bot 설정"),
            Width = 500,
            Height = 520,
            StartPosition = FormStartPosition.CenterScreen,
            FormBorderStyle = FormBorderStyle.FixedDialog,
            MaximizeBox = false,
            MinimizeBox = false,
            BackColor = BgDark,
            ForeColor = FgWhite,
        };

        // Setup guide link
        var linkLabel = new LinkLabel() { Text = L("Open Setup Guide", "설정 가이드 열기"), Left = 15, Top = 10, Width = 450, Height = 20, LinkColor = LinkBlue, BackColor = Color.Transparent };
        linkLabel.LinkClicked += (s, ev) => { Process.Start("https://github.com/chadingTV/codex-discord/blob/main/SETUP.md"); };
        form.Controls.Add(linkLabel);

        // Issues link
        var issueLabel = new LinkLabel() { Text = L("Bug Report / Feature Request (GitHub Issues)", "버그 신고 / 기능 요청 (GitHub Issues)"), Left = 15, Top = 32, Width = 450, Height = 20, LinkColor = LinkBlue, BackColor = Color.Transparent };
        issueLabel.LinkClicked += (s, ev) => { Process.Start("https://github.com/chadingTV/codex-discord/issues"); };
        form.Controls.Add(issueLabel);

        string[][] fields = new string[][] {
            new string[] { "DISCORD_BOT_TOKEN", "Discord Bot Token" },
            new string[] { "DISCORD_GUILD_ID", "Discord Guild ID (Server ID)" },
            new string[] { "ALLOWED_USER_IDS", L("Allowed User IDs (comma-separated)", "허용된 사용자 ID (쉼표로 구분)") },
            new string[] { "BASE_PROJECT_DIR", L("Base Project Directory", "기본 프로젝트 디렉토리") },
            new string[] { "RATE_LIMIT_PER_MINUTE", L("Rate Limit Per Minute", "분당 요청 제한") },
        };

        string[] defaults = new string[] { "", "", "", "", "10" };
        string[] placeholders = new string[] {
            L("Paste your bot token here", "봇 토큰을 여기에 붙여넣으세요"),
            L("Right-click server > Copy Server ID", "서버 우클릭 > 서버 ID 복사"),
            L("e.g. 123456789,987654321", "예: 123456789,987654321"),
            L("e.g. C:\\Users\\you\\projects", "예: C:\\Users\\you\\projects"),
            "10"
        };
        // Placeholder values from .env.example that should be treated as empty
        var exampleValues = new System.Collections.Generic.HashSet<string>() {
            "your_bot_token_here", "your_server_id_here", "your_user_id_here",
            "/Users/yourname/projects", "/Users/you/projects", "C:\\Users\\yourname\\projects"
        };

        SetDarkTitleBar(form);

        var tbFont = new Font(FontFamily.GenericSansSerif, 10f);
        var textBoxes = new TextBox[fields.Length];
        int y = 58;

        for (int i = 0; i < fields.Length; i++)
        {
            var label = new Label() { Text = fields[i][1], Left = 15, Top = y, Width = 450, Font = new Font(FontFamily.GenericSansSerif, 9, FontStyle.Bold), ForeColor = FgWhite, BackColor = Color.Transparent };
            form.Controls.Add(label);
            y += 22;

            if (fields[i][0] == "BASE_PROJECT_DIR")
            {
                var tb = new TextBox() { Left = 15, Top = y, Width = 360, BackColor = BgPanel, ForeColor = FgWhite, BorderStyle = BorderStyle.FixedSingle, Font = tbFont };
                string val = "";
                env.TryGetValue(fields[i][0], out val);
                if (val != null && exampleValues.Contains(val)) val = "";
                if (val != null && val != "")
                    tb.Text = val;
                else
                {
                    string hint = placeholders[i];
                    tb.HandleCreated += (s2, e2) => {
                        SendMessage(((TextBox)s2).Handle, EM_SETCUEBANNER, IntPtr.Zero, hint);
                    };
                }
                form.Controls.Add(tb);
                textBoxes[i] = tb;

                var browseBtn = new Button() { Text = L("Browse...", "찾아보기..."), Left = 380, Top = y, Width = 85, Height = tb.Height, FlatStyle = FlatStyle.Flat, BackColor = BgButton, ForeColor = FgWhite };
                browseBtn.FlatAppearance.BorderSize = 0;
                int idx = i;
                browseBtn.Click += (s, ev) =>
                {
                    using (var fbd = new FolderBrowserDialog())
                    {
                        fbd.Description = L("Select Base Project Directory", "기본 프로젝트 디렉토리 선택");
                        if (textBoxes[idx].Text != "") fbd.SelectedPath = textBoxes[idx].Text;
                        if (fbd.ShowDialog() == DialogResult.OK)
                        {
                            textBoxes[idx].Text = fbd.SelectedPath;
                        }
                    }
                };
                form.Controls.Add(browseBtn);
            }
            else
            {
                var tb = new TextBox() { Left = 15, Top = y, Width = 450, BackColor = BgPanel, ForeColor = FgWhite, BorderStyle = BorderStyle.FixedSingle, Font = tbFont };
                string val = "";
                env.TryGetValue(fields[i][0], out val);
                if (val != null && exampleValues.Contains(val)) val = "";

                if (fields[i][0] == "DISCORD_BOT_TOKEN" && val != null && val.Length > 10)
                {
                    tb.HandleCreated += (s2, e2) => {
                        SendMessage(((TextBox)s2).Handle, EM_SETCUEBANNER, IntPtr.Zero,
                            "****" + val.Substring(val.Length - 6) + L(" (enter full token to change)", " (변경하려면 전체 토큰 입력)"));
                    };
                }
                else if (val != null && val != "")
                {
                    tb.Text = val;
                }
                else
                {
                    tb.Text = defaults[i];
                    if (defaults[i] == "")
                    {
                        string hint = placeholders[i];
                        tb.HandleCreated += (s2, e2) => {
                            SendMessage(((TextBox)s2).Handle, EM_SETCUEBANNER, IntPtr.Zero, hint);
                        };
                    }
                }

                form.Controls.Add(tb);
                textBoxes[i] = tb;
            }
            y += 34;
        }

        // Show Cost radio buttons
        var showCostLabel = new Label() { Text = L("Show Cost", "비용 표시"), Left = 15, Top = y, Width = 450, Font = new Font(FontFamily.GenericSansSerif, 9, FontStyle.Bold), ForeColor = FgWhite, BackColor = Color.Transparent };
        form.Controls.Add(showCostLabel);
        y += 22;

        string showCostVal = "true";
        env.TryGetValue("SHOW_COST", out showCostVal);
        if (showCostVal == null) showCostVal = "true";
        bool showCostEnabled = (showCostVal.ToLower() != "false");

        var radioTrue = new RadioButton() { Text = "True", Left = 15, Top = y, Width = 80, Height = 22, ForeColor = FgWhite, BackColor = Color.Transparent, Font = new Font(FontFamily.GenericSansSerif, 9.5f), Checked = showCostEnabled };
        var radioFalse = new RadioButton() { Text = "False", Left = 100, Top = y, Width = 80, Height = 22, ForeColor = FgWhite, BackColor = Color.Transparent, Font = new Font(FontFamily.GenericSansSerif, 9.5f), Checked = !showCostEnabled };
        var costNote = new Label() { Text = L("(set False for Max plan)", "(Max 요금제는 False)"), Left = 190, Top = y + 2, Width = 250, Height = 20, ForeColor = FgDimGray, BackColor = Color.Transparent, Font = new Font(FontFamily.GenericSansSerif, 8.5f) };
        form.Controls.Add(radioTrue);
        form.Controls.Add(radioFalse);
        form.Controls.Add(costNote);
        y += 34;

        var saveBtn = MakeDarkButton(L("Save", "저장"), 300, y, 80, 32, AccentBlue, Color.White);
        var cancelBtn = MakeDarkButton(L("Cancel", "취소"), 385, y, 80, 32, BgButton, FgWhite);

        saveBtn.Click += (s, ev) =>
        {
            string[] values = new string[fields.Length];
            for (int i = 0; i < fields.Length; i++)
            {
                values[i] = textBoxes[i].Text.Trim();
                if (values[i] == "" && fields[i][0] == "DISCORD_BOT_TOKEN")
                {
                    string existing = "";
                    env.TryGetValue(fields[i][0], out existing);
                    values[i] = existing ?? "";
                }
                if (values[i] == "") values[i] = defaults[i];
            }

            if (values[0] == "" || values[1] == "" || values[2] == "")
            {
                MessageBox.Show(
                    L("Bot Token, Guild ID (Server ID), and User IDs are required.",
                      "Bot Token, Guild ID (서버 ID), User IDs는 필수 항목입니다."),
                    L("Required Fields Missing", "필수 항목 누락"), MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            using (var sw = new StreamWriter(envPath))
            {
                for (int i = 0; i < fields.Length; i++)
                {
                    sw.WriteLine(fields[i][0] + "=" + values[i]);
                }
                sw.WriteLine("# Show estimated API cost in task results (set false for Max plan users)");
                sw.WriteLine("SHOW_COST=" + (radioTrue.Checked ? "true" : "false"));
            }

            form.DialogResult = DialogResult.OK;
            form.Close();
        };

        cancelBtn.Click += (s, ev) => { form.Close(); };

        form.Controls.Add(saveBtn);
        form.Controls.Add(cancelBtn);
        form.AcceptButton = saveBtn;
        form.CancelButton = cancelBtn;
        form.ShowDialog();

        UpdateStatus();
        BuildMenu();
    }

    private System.Collections.Generic.Dictionary<string, string> LoadEnv()
    {
        var env = new System.Collections.Generic.Dictionary<string, string>();
        if (!File.Exists(envPath)) return env;

        foreach (var line in File.ReadAllLines(envPath))
        {
            string trimmed = line.Trim();
            if (trimmed.StartsWith("#") || !trimmed.Contains("=")) continue;
            int idx = trimmed.IndexOf('=');
            string key = trimmed.Substring(0, idx);
            string val = trimmed.Substring(idx + 1);
            env[key] = val;
        }
        return env;
    }

    private Form controlPanel = null;

    // Dark theme colors
    private static readonly Color BgDark = Color.FromArgb(42, 42, 42);
    private static readonly Color BgPanel = Color.FromArgb(58, 58, 58);
    private static readonly Color BgButton = Color.FromArgb(72, 72, 72);
    private static readonly Color FgWhite = Color.FromArgb(230, 230, 230);
    private static readonly Color FgGray = Color.FromArgb(150, 150, 150);
    private static readonly Color FgDimGray = Color.FromArgb(110, 110, 110);
    private static readonly Color SepColor = Color.FromArgb(65, 65, 65);
    private static readonly Color BtnStop = Color.FromArgb(140, 60, 60);
    private static readonly Color BtnRestart = Color.FromArgb(130, 110, 55);
    private static readonly Color BtnSettings = Color.FromArgb(50, 70, 130);
    private static readonly Color LinkBlue = Color.FromArgb(100, 160, 240);
    private static readonly Color AccentBlue = Color.FromArgb(66, 133, 244);

    private static GraphicsPath RoundedRect(Rectangle bounds, int radius)
    {
        var path = new GraphicsPath();
        int d = radius * 2;
        path.AddArc(bounds.X, bounds.Y, d, d, 180, 90);
        path.AddArc(bounds.Right - d, bounds.Y, d, d, 270, 90);
        path.AddArc(bounds.Right - d, bounds.Bottom - d, d, d, 0, 90);
        path.AddArc(bounds.X, bounds.Bottom - d, d, d, 90, 90);
        path.CloseFigure();
        return path;
    }

    private static void SetDarkTitleBar(Form form)
    {
        try
        {
            int value = 1;
            DwmSetWindowAttribute(form.Handle, DWMWA_USE_IMMERSIVE_DARK_MODE, ref value, sizeof(int));
        }
        catch { }
    }

    private Button MakeDarkButton(string text, int left, int top, int width, int height, Color bgColor, Color fgColor)
    {
        var btn = new Button()
        {
            Text = text, Left = left, Top = top, Width = width, Height = height,
            FlatStyle = FlatStyle.Flat, BackColor = bgColor, ForeColor = fgColor,
            Font = new Font(FontFamily.GenericSansSerif, 9.5f, FontStyle.Bold),
            Cursor = Cursors.Hand
        };
        btn.FlatAppearance.BorderSize = 0;
        btn.FlatAppearance.MouseOverBackColor = Color.FromArgb(
            Math.Min(bgColor.R + 20, 255), Math.Min(bgColor.G + 20, 255), Math.Min(bgColor.B + 20, 255));
        using (var path = RoundedRect(new Rectangle(0, 0, width, height), 8))
            btn.Region = new Region(path);
        return btn;
    }

    private void ShowControlPanel()
    {
        // If already open, bring to front
        if (controlPanel != null && !controlPanel.IsDisposed)
        {
            controlPanel.Activate();
            return;
        }

        int panelWidth = 460;

        controlPanel = new Form()
        {
            Text = "Codex Discord Bot",
            Width = panelWidth,
            Height = 590,
            StartPosition = FormStartPosition.CenterScreen,
            FormBorderStyle = FormBorderStyle.FixedDialog,
            MaximizeBox = false,
            MinimizeBox = false,
            BackColor = BgDark,
            ForeColor = FgWhite,
        };

        string icoPath = Path.Combine(botDir, "docs", "icon.ico");
        if (File.Exists(icoPath))
            controlPanel.Icon = new Icon(icoPath);

        SetDarkTitleBar(controlPanel);

        RebuildControlPanel();
        if (usageLastFetched == null || (DateTime.Now - usageLastFetched.Value).TotalMinutes > 5)
            RefreshUsageAsync(true);
        controlPanel.ShowDialog();
        controlPanel = null;
    }

    private void RebuildControlPanel()
    {
        if (controlPanel == null || controlPanel.IsDisposed) return;

        // Remember position
        Point pos = controlPanel.Location;
        bool wasVisible = controlPanel.Visible;
        lastPanelRunning = IsRunning();

        controlPanel.SuspendLayout();
        controlPanel.Controls.Clear();

        bool running = IsRunning();
        bool hasEnv = IsEnvConfigured();

        int panelWidth = controlPanel.Width;
        int btnWidth = panelWidth - 60;
        int halfBtnWidth = (btnWidth - 10) / 2;

        int y = 20;

        // Header: Icon + Title + Version + Language toggle
        string iconPngPath = Path.Combine(botDir, "docs", "icon-rounded.png");
        if (File.Exists(iconPngPath))
        {
            var iconBox = new PictureBox()
            {
                Left = 25, Top = y, Width = 48, Height = 48,
                SizeMode = PictureBoxSizeMode.Zoom,
                BackColor = Color.Transparent
            };
            try { iconBox.Image = Image.FromFile(iconPngPath); } catch { }
            controlPanel.Controls.Add(iconBox);
        }

        var titleLabel = new Label()
        {
            Text = "Codex Discord Bot",
            Left = 82, Top = y,
            Width = 250, Height = 24,
            Font = new Font(FontFamily.GenericSansSerif, 14, FontStyle.Bold),
            ForeColor = FgWhite, BackColor = Color.Transparent
        };
        controlPanel.Controls.Add(titleLabel);

        var verSubLabel = new Label()
        {
            Text = currentVersion,
            Left = 82, Top = y + 26,
            Width = 250, Height = 16,
            Font = new Font(FontFamily.GenericSansSerif, 9),
            ForeColor = FgGray, BackColor = Color.Transparent
        };
        controlPanel.Controls.Add(verSubLabel);

        // Language toggle - top right
        var enBtn = new Label()
        {
            Text = "EN",
            Left = panelWidth - 110, Top = y + 6,
            Width = 32, Height = 22,
            TextAlign = ContentAlignment.MiddleCenter,
            Font = new Font(FontFamily.GenericSansSerif, 9, !isKorean ? FontStyle.Bold : FontStyle.Regular),
            ForeColor = !isKorean ? Color.White : FgDimGray,
            BackColor = !isKorean ? AccentBlue : BgButton,
            Cursor = Cursors.Hand
        };
        var divLabel = new Label()
        {
            Text = "|",
            Left = panelWidth - 78, Top = y + 6,
            Width = 10, Height = 22,
            TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = SepColor, BackColor = Color.Transparent
        };
        var krBtn = new Label()
        {
            Text = "KR",
            Left = panelWidth - 68, Top = y + 6,
            Width = 32, Height = 22,
            TextAlign = ContentAlignment.MiddleCenter,
            Font = new Font(FontFamily.GenericSansSerif, 9, isKorean ? FontStyle.Bold : FontStyle.Regular),
            ForeColor = isKorean ? Color.White : FgDimGray,
            BackColor = isKorean ? AccentBlue : BgButton,
            Cursor = Cursors.Hand
        };
        enBtn.Click += (s, ev) => { SetLanguage(false); RebuildControlPanel(); };
        krBtn.Click += (s, ev) => { SetLanguage(true); RebuildControlPanel(); };
        controlPanel.Controls.Add(enBtn);
        controlPanel.Controls.Add(divLabel);
        controlPanel.Controls.Add(krBtn);

        y += 58;

        // Separator after header
        var headerSep = new Label() { Left = 25, Top = y, Width = btnWidth, Height = 1, BackColor = SepColor };
        controlPanel.Controls.Add(headerSep);
        y += 15;

        // Status indicator
        string statusText = !hasEnv ? L("Setup Required", "설정 필요") : botStarting ? L("Starting...", "시작 중...") : (running ? L("Running", "실행 중") : L("Stopped", "중지됨"));
        Color statusColor = !hasEnv ? Color.Orange : botStarting ? Color.Yellow : (running ? Color.LimeGreen : Color.Red);
        var statusPanel = new Panel() { Left = 25, Top = y, Width = btnWidth, Height = 50, BackColor = BgPanel };
        using (var path = RoundedRect(new Rectangle(0, 0, btnWidth, 50), 8))
            statusPanel.Region = new Region(path);
        var statusDot = new Label() { Left = 14, Top = 14, Width = 24, Height = 24, Text = "", BackColor = Color.Transparent };
        statusDot.Paint += (s, e) => {
            e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
            using (var brush = new SolidBrush(statusColor))
                e.Graphics.FillEllipse(brush, 2, 2, 18, 18);
        };
        statusPanel.Controls.Add(statusDot);
        var statusLabel = new Label() {
            Left = 42, Top = 15, Width = 320, Height = 24,
            Text = statusText,
            Font = new Font(FontFamily.GenericSansSerif, 12, FontStyle.Bold),
            ForeColor = FgWhite, BackColor = Color.Transparent
        };
        statusPanel.Controls.Add(statusLabel);
        controlPanel.Controls.Add(statusPanel);
        y += 62;

        var usageRows = GetUsageRows(usageData);
        if (usageRows.Count > 0)
        {
            int usageHeight = 90 + usageRows.Count * 52 + (usageLastFetched.HasValue ? 24 : 0);
            if (usageData.ContainsKey("planType")) usageHeight += 20;

            var usagePanel = new Panel() { Left = 25, Top = y, Width = btnWidth, Height = usageHeight, BackColor = BgPanel, Cursor = Cursors.Hand };
            using (var path = RoundedRect(new Rectangle(0, 0, btnWidth, usageHeight), 8))
                usagePanel.Region = new Region(path);
            usagePanel.Click += OpenUsagePage;
            controlPanel.Controls.Add(usagePanel);

            int uy = 12;
            var usageTitle = new Label()
            {
                Text = L("Codex Usage", "Codex 사용량"),
                Left = 14, Top = uy, Width = 220, Height = 18,
                Font = new Font(FontFamily.GenericSansSerif, 10, FontStyle.Bold),
                ForeColor = FgWhite, BackColor = Color.Transparent
            };
            usageTitle.Click += OpenUsagePage;
            usagePanel.Controls.Add(usageTitle);

            var refreshBtn = MakeDarkButton(L("Refresh", "새로고침"), btnWidth - 94, 10, 80, 28, BgButton, FgWhite);
            refreshBtn.Click += (s, ev) => { RefreshUsageAsync(true); };
            usagePanel.Controls.Add(refreshBtn);
            uy += 26;

            if (usageData.ContainsKey("planType"))
            {
                var planLabel = new Label()
                {
                    Text = L("Plan", "플랜") + ": " + Convert.ToString(usageData["planType"]),
                    Left = 14, Top = uy, Width = btnWidth - 28, Height = 16,
                    Font = new Font(FontFamily.GenericSansSerif, 8.5f),
                    ForeColor = FgDimGray, BackColor = Color.Transparent
                };
                planLabel.Click += OpenUsagePage;
                usagePanel.Controls.Add(planLabel);
                uy += 20;
            }

            string previousTitle = null;
            foreach (var row in usageRows)
            {
                string bucketTitle = row["bucketTitle"] == null ? null : Convert.ToString(row["bucketTitle"]);
                var window = row["window"] as Dictionary<string, object>;
                if (window == null) continue;

                if (!string.IsNullOrWhiteSpace(bucketTitle) && bucketTitle != previousTitle)
                {
                    var bucketLabel = new Label()
                    {
                        Text = bucketTitle,
                        Left = 14, Top = uy, Width = btnWidth - 28, Height = 16,
                        Font = new Font(FontFamily.GenericSansSerif, 8.5f, FontStyle.Bold),
                        ForeColor = FgGray, BackColor = Color.Transparent
                    };
                    bucketLabel.Click += OpenUsagePage;
                    usagePanel.Controls.Add(bucketLabel);
                    uy += 18;
                    previousTitle = bucketTitle;
                }

                int percentLeft = UsagePercentLeft(window);
                var nameLabel = new Label()
                {
                    Text = UsageLabel(window),
                    Left = 14, Top = uy, Width = 200, Height = 18,
                    Font = new Font(FontFamily.GenericSansSerif, 9.5f, FontStyle.Bold),
                    ForeColor = FgGray, BackColor = Color.Transparent
                };
                nameLabel.Click += OpenUsagePage;
                usagePanel.Controls.Add(nameLabel);

                var pctLabel = new Label()
                {
                    Text = percentLeft + "% " + L("left", "남음"),
                    Left = btnWidth - 130, Top = uy, Width = 116, Height = 18,
                    TextAlign = ContentAlignment.MiddleRight,
                    Font = new Font(FontFamily.GenericSansSerif, 9.5f, FontStyle.Bold),
                    ForeColor = UsageBarColor(percentLeft), BackColor = Color.Transparent
                };
                pctLabel.Click += OpenUsagePage;
                usagePanel.Controls.Add(pctLabel);
                uy += 22;

                var barBg = new Panel()
                {
                    Left = 14, Top = uy, Width = btnWidth - 28, Height = 10,
                    BackColor = Color.FromArgb(56, 56, 56)
                };
                barBg.Click += OpenUsagePage;
                usagePanel.Controls.Add(barBg);

                int fillWidth = (int)Math.Round((btnWidth - 28) * (percentLeft / 100.0));
                if (fillWidth > 0)
                {
                    var barFill = new Panel()
                    {
                        Left = 14, Top = uy, Width = fillWidth, Height = 10,
                        BackColor = UsageBarColor(percentLeft)
                    };
                    barFill.Click += OpenUsagePage;
                    usagePanel.Controls.Add(barFill);
                    barFill.BringToFront();
                }
                uy += 14;

                string resetText = UsageResetText(window);
                if (!string.IsNullOrWhiteSpace(resetText))
                {
                    var resetLabel = new Label()
                    {
                        Text = resetText,
                        Left = 14, Top = uy, Width = btnWidth - 28, Height = 14,
                        Font = new Font(FontFamily.GenericSansSerif, 8),
                        ForeColor = FgDimGray, BackColor = Color.Transparent
                    };
                    resetLabel.Click += OpenUsagePage;
                    usagePanel.Controls.Add(resetLabel);
                    uy += 18;
                }
                else
                {
                    uy += 6;
                }
            }

            string fetchedText = FetchedLabel();
            if (!string.IsNullOrWhiteSpace(fetchedText))
            {
                var fetchedLabel = new Label()
                {
                    Text = fetchedText,
                    Left = 14, Top = uy, Width = btnWidth - 28, Height = 14,
                    TextAlign = ContentAlignment.MiddleRight,
                    Font = new Font(FontFamily.GenericSansSerif, 8),
                    ForeColor = FgDimGray, BackColor = Color.Transparent
                };
                fetchedLabel.Click += OpenUsagePage;
                usagePanel.Controls.Add(fetchedLabel);
            }

            y += usageHeight + 12;
        }
        else if (hasEnv)
        {
            var loadUsageBtn = MakeDarkButton(L("Load Usage Info", "사용량 정보 불러오기"), 25, y, btnWidth, 42, BgButton, FgWhite);
            loadUsageBtn.Click += (s, ev) => { RefreshUsageAsync(true); };
            controlPanel.Controls.Add(loadUsageBtn);
            y += 54;
        }

        // Bot control buttons
        if (hasEnv)
        {
            if (running)
            {
                var stopBtn = MakeDarkButton(L("Stop Bot", "봇 중지"), 25, y, halfBtnWidth, 42, BtnStop, Color.FromArgb(230, 120, 120));
                stopBtn.Click += (s, ev) => { StopBot(null, null); RebuildControlPanel(); };
                controlPanel.Controls.Add(stopBtn);

                var restartBtn = MakeDarkButton(L("Restart Bot", "봇 재시작"), 25 + halfBtnWidth + 10, y, halfBtnWidth, 42, BtnRestart, Color.FromArgb(220, 180, 90));
                restartBtn.Click += (s, ev) => { RestartBot(null, null); };
                controlPanel.Controls.Add(restartBtn);
            }
            else if (botStarting)
            {
                var startingBtn = MakeDarkButton(L("Starting...", "시작 중..."), 25, y, btnWidth, 42, BgPanel, FgDimGray);
                startingBtn.Enabled = false;
                controlPanel.Controls.Add(startingBtn);
            }
            else
            {
                var startBtn = MakeDarkButton(L("Start Bot", "봇 시작"), 25, y, btnWidth, 42, BgButton, FgWhite);
                startBtn.Click += (s, ev) => { StartBot(null, null); };
                controlPanel.Controls.Add(startBtn);
            }
            y += 52;
        }

        // Settings button
        var settingsBtn = MakeDarkButton(L("Settings...", "설정..."), 25, y, btnWidth, 42, BtnSettings, Color.FromArgb(100, 160, 240));
        settingsBtn.Click += (s, ev) => {
            OpenSettings(null, null);
            UpdateStatus();
            BuildMenu();
        };
        controlPanel.Controls.Add(settingsBtn);
        y += 50;

        if (hasEnv)
        {
            // View Log
            var logBtn = MakeDarkButton(L("View Log", "로그 보기"), 25, y, halfBtnWidth, 42, BgButton, FgWhite);
            logBtn.Click += (s, ev) => { OpenLog(null, null); };
            controlPanel.Controls.Add(logBtn);

            // Open Folder
            var folderBtn = MakeDarkButton(L("Open Folder", "폴더 열기"), 25 + halfBtnWidth + 10, y, halfBtnWidth, 42, BgButton, FgWhite);
            folderBtn.Click += (s, ev) => { OpenFolder(null, null); };
            controlPanel.Controls.Add(folderBtn);
            y += 52;
        }

        // Separator line
        var sep1 = new Label() { Left = 25, Top = y, Width = btnWidth, Height = 1, BackColor = SepColor };
        controlPanel.Controls.Add(sep1);
        y += 12;

        // Auto-start checkbox
        var autoCheck = new CheckBox()
        {
            Text = L("Auto Run on Startup", "시작 시 자동 실행"),
            Left = 25, Top = y, Width = btnWidth, Height = 22,
            Font = new Font(FontFamily.GenericSansSerif, 9.5f),
            ForeColor = FgWhite, BackColor = Color.Transparent,
            Checked = IsAutoStartEnabled()
        };
        autoCheck.CheckedChanged += (s, ev) => { ToggleAutoStart(null, null); };
        controlPanel.Controls.Add(autoCheck);
        y += 36;

        // Update button
        if (updateAvailable)
        {
            var updateBtn = MakeDarkButton(
                L("Update Available - Click to Update", "업데이트 가능 - 클릭하여 업데이트"),
                25, y, btnWidth, 42, AccentBlue, Color.White);
            updateBtn.Click += (s, ev) => { controlPanel.Close(); PerformUpdate(null, null); };
            controlPanel.Controls.Add(updateBtn);
            y += 52;
        }
        else
        {
            var checkUpdateBtn = MakeDarkButton(L("Check for Updates", "업데이트 확인"), 25, y, btnWidth, 42, BgButton, FgWhite);
            checkUpdateBtn.Click += (s, ev) => {
                CheckForUpdates();
                if (updateAvailable)
                {
                    RebuildControlPanel();
                }
                else
                {
                    MessageBox.Show(
                        L("You are running the latest version.", "최신 버전을 사용 중입니다."),
                        L("No Updates", "업데이트 없음"),
                        MessageBoxButtons.OK, MessageBoxIcon.Information);
                }
            };
            controlPanel.Controls.Add(checkUpdateBtn);
            y += 52;
        }

        // Separator line
        var sep2 = new Label() { Left = 25, Top = y, Width = btnWidth, Height = 1, BackColor = SepColor };
        controlPanel.Controls.Add(sep2);
        y += 12;

        // Info message
        var infoLabel = new Label() {
            Text = L("Closing this window does not stop the bot.\nThe bot runs in the background. Check the tray icon for status.",
                      "이 창을 닫아도 봇은 중지되지 않습니다.\n봇은 백그라운드에서 실행됩니다. 트레이 아이콘에서 상태를 확인하세요."),
            Left = 25, Top = y, Width = btnWidth, Height = 40,
            ForeColor = FgDimGray, BackColor = Color.Transparent,
            Font = new Font(FontFamily.GenericSansSerif, 8.5f)
        };
        controlPanel.Controls.Add(infoLabel);
        y += 48;

        // Quit button
        var quitBtn = MakeDarkButton(L("Quit Bot", "봇 종료"), 25, y, btnWidth, 42, BgButton, FgGray);
        quitBtn.Click += (s, ev) => { controlPanel.Close(); QuitAll(null, null); };
        controlPanel.Controls.Add(quitBtn);
        y += 52;

        // Separator line
        var sep3 = new Label() { Left = 25, Top = y, Width = btnWidth, Height = 1, BackColor = SepColor };
        controlPanel.Controls.Add(sep3);
        y += 12;

        // GitHub link
        var ghLink = new LinkLabel()
        {
            Text = "Upstream GitHub Repo",
            Left = 25, Top = y, Width = btnWidth, Height = 20,
            TextAlign = ContentAlignment.MiddleCenter,
            Font = new Font(FontFamily.GenericSansSerif, 8.5f),
            LinkColor = LinkBlue, BackColor = Color.Transparent
        };
        ghLink.LinkClicked += (s, ev) => { Process.Start("https://github.com/chadingTV/codex-discord"); };
        controlPanel.Controls.Add(ghLink);
        y += 22;

        // Issues link
        var issueLink = new LinkLabel()
        {
            Text = L("Bug Report / Feature Request (GitHub Issues)", "버그 신고 / 기능 요청 (GitHub Issues)"),
            Left = 25, Top = y, Width = btnWidth, Height = 20,
            TextAlign = ContentAlignment.MiddleCenter,
            Font = new Font(FontFamily.GenericSansSerif, 8.5f),
            LinkColor = LinkBlue, BackColor = Color.Transparent
        };
        issueLink.LinkClicked += (s, ev) => { Process.Start("https://github.com/chadingTV/codex-discord/issues"); };
        controlPanel.Controls.Add(issueLink);
        y += 22;

        // Star request
        var starLabel = new Label()
        {
            Text = L("If you find this useful, please give it a Star on GitHub!",
                      "유용하셨다면 GitHub에서 Star를 눌러주세요!"),
            Left = 25, Top = y, Width = btnWidth, Height = 18,
            TextAlign = ContentAlignment.MiddleCenter,
            Font = new Font(FontFamily.GenericSansSerif, 8f),
            ForeColor = FgDimGray, BackColor = Color.Transparent
        };
        controlPanel.Controls.Add(starLabel);
        y += 28;

        controlPanel.Height = y + 45;

        // Restore position if it was already visible
        if (wasVisible)
        {
            controlPanel.Location = pos;
        }

        controlPanel.ResumeLayout(true);
    }

    private void QuitAll(object sender, EventArgs e)
    {
        KillBot();
        trayIcon.Visible = false;
        Application.Exit();
    }

    private void RunCmd(string command, bool wait)
    {
        var proc = new Process();
        proc.StartInfo.FileName = "cmd.exe";
        proc.StartInfo.Arguments = "/c " + command;
        proc.StartInfo.UseShellExecute = false;
        proc.StartInfo.CreateNoWindow = true;
        proc.Start();
        if (wait) proc.WaitForExit();
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        trayIcon.Visible = false;
        base.OnFormClosing(e);
    }

    [STAThread]
    static void Main()
    {
        // Kill any other CodexBotTray instances (handles leftover duplicates from updates)
        int myPid = Process.GetCurrentProcess().Id;
        foreach (var proc in Process.GetProcessesByName("CodexBotTray"))
        {
            if (proc.Id != myPid)
            {
                try { proc.Kill(); proc.WaitForExit(3000); } catch { }
            }
        }
        Thread.Sleep(500);

        // Single instance check using named Mutex
        bool createdNew;
        using (var mutex = new Mutex(true, "CodexBotTray_SingleInstance", out createdNew))
        {
            if (!createdNew)
            {
                // Another instance is already running - exit silently
                return;
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new CodexBotTray());
        }
    }
}
