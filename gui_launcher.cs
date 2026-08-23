// gui_launcher.cs - 相机拷卡 GUI 启动器（编译为无控制台窗口的 exe）
// 用法：找到 main.py（exe 同级 / 上级 / 上上级），用 pythonw.exe 运行它。
// 源码保持纯 ASCII，避免 csc 编码问题。
using System;
using System.Diagnostics;
using System.IO;

class GuiLauncher
{
    [STAThread]
    static int Main(string[] args)
    {
        string exeDir = AppDomain.CurrentDomain.BaseDirectory;
        string script = FindScript(exeDir);
        if (script == null)
        {
            ShowError("Cannot find main.py near " + exeDir
                + "\nPlease keep the exe inside the camera_copy_tool folder.");
            return 1;
        }
        string pythonw = FindPython("pythonw.exe");
        if (pythonw == null)
        {
            System.Windows.Forms.DialogResult r = System.Windows.Forms.MessageBox.Show(
                "未检测到 Python（pythonw.exe）。\n\nCoCa 需要 Python 3 才能运行。\n\n"
                + "是否打开 Python 官网，按引导自行下载并安装？",
                "CoCa 环境检测",
                System.Windows.Forms.MessageBoxButtons.YesNo,
                System.Windows.Forms.MessageBoxIcon.Warning);
            if (r == System.Windows.Forms.DialogResult.Yes)
            {
                try { System.Diagnostics.Process.Start("https://www.python.org/downloads/"); } catch { }
            }
            return 1;
        }
        try
        {
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = pythonw;
            psi.Arguments = "\"" + script + "\"";
            Process.Start(psi);
            return 0;
        }
        catch (Exception ex)
        {
            ShowError("Failed to start program: " + ex.Message);
            return 1;
        }
    }

    static string FindScript(string exeDir)
    {
        string[] candidates = {
            Path.Combine(exeDir, "main.py"),
            Path.Combine(Path.GetFullPath(Path.Combine(exeDir, "..")), "main.py"),
            Path.Combine(Path.GetFullPath(Path.Combine(exeDir, "..", "..")), "main.py")
        };
        foreach (string c in candidates)
        {
            try { if (File.Exists(c)) return Path.GetFullPath(c); } catch { }
        }
        return null;
    }

    static string FindPython(string name)
    {
        string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        string[] roots = {
            Path.Combine(local, "Programs", "Python"),
            Path.Combine(local, "Python")
        };
        foreach (string root in roots)
        {
            try
            {
                foreach (string dir in Directory.GetDirectories(root))
                {
                    string full = Path.Combine(dir, name);
                    if (File.Exists(full)) return full;
                }
            }
            catch { }
        }
        string pathEnv = Environment.GetEnvironmentVariable("PATH") ?? "";
        foreach (string dir in pathEnv.Split(';'))
        {
            string d = (dir ?? "").Trim().Trim('"');
            if (d.Length == 0) continue;
            if (d.IndexOf("WindowsApps", StringComparison.OrdinalIgnoreCase) >= 0) continue;
            try
            {
                string full = Path.Combine(d, name);
                if (File.Exists(full)) return full;
            }
            catch { }
        }
        return null;
    }

    static void ShowError(string msg)
    {
        try
        {
            System.Windows.Forms.MessageBox.Show(msg, "Camera Copy Tool",
                System.Windows.Forms.MessageBoxButtons.OK,
                System.Windows.Forms.MessageBoxIcon.Error);
        }
        catch { }
    }
}
