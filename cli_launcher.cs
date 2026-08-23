// cli_launcher.cs - 相机拷卡 CLI 启动器（控制台窗口，透传参数与退出码）
// 用法：相机拷卡-cli.exe --cli <源目录> <目标根目录> [选项]
using System;
using System.Diagnostics;
using System.IO;
using System.Text;

class CliLauncher
{
    static int Main(string[] args)
    {
        string exeDir = AppDomain.CurrentDomain.BaseDirectory;
        string script = FindScript(exeDir);
        if (script == null)
        {
            Console.Error.WriteLine("Cannot find main.py near " + exeDir);
            return 1;
        }
        string python = FindPython("python.exe");
        if (python == null)
        {
            Console.Error.WriteLine("Python (python.exe) not found. Please install Python 3 first.");
            return 1;
        }
        try
        {
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = python;
            psi.UseShellExecute = false;
            // 不设置 WorkingDirectory：继承调用者当前目录，相对路径按调用位置解析
            psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            StringBuilder argb = new StringBuilder();
            argb.Append('"').Append(script).Append('"');
            foreach (string a in args)
            {
                argb.Append(" \"").Append(a.Replace("\"", "\\\"")).Append('"');
            }
            psi.Arguments = argb.ToString();
            Process p = Process.Start(psi);
            p.WaitForExit();
            return p.ExitCode;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("Failed to start: " + ex.Message);
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
}
