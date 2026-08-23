// installer.cs - CoCa 安装程序（自包含：内嵌运行文件，安装到目标目录）
// 编译：
//   csc /target:winexe /out:CoCa_Setup.exe /r:System.Windows.Forms.dll \
//     /resource:main.py,main.py /resource:copier.py,copier.py /resource:archive.py,archive.py \
//     /resource:config.py,config.py /resource:glass.py,glass.py /resource:dist\CoCa.exe,CoCa.exe \
//     installer.cs
// 用法：
//   双击（图形界面，带进度条，装完提示"安装成功"）；
//   --silent --dir <目录>  静默安装；  --extract --dir <目录>  仅解压不建快捷方式。
using System;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

public class SetupForm : Form
{
    TextBox dirBox;
    Label status;
    ProgressBar prog;
    Button installBtn, cancelBtn;

    static string[] AppFiles = { "main.py", "copier.py", "archive.py", "config.py", "glass.py", "CoCa.exe", "CoCa_Uninstall.exe", "icon.ico" };
    const int EXTRA_STEPS = 3;   // 桌面快捷方式 / 开始菜单 / 注册表

    public SetupForm()
    {
        Text = "CoCa 安装程序";
        ClientSize = new Size(560, 262);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;

        var title = new Label { Text = "CoCa 相机拷卡工具", Left = 20, Top = 18,
                                Font = new Font("SimHei", 13, FontStyle.Bold),
                                ForeColor = Color.FromArgb(0x1C, 0x2B, 0x4A), AutoSize = true };
        var info = new Label { Text = "将安装到：", Left = 20, Top = 58, AutoSize = true };
        dirBox = new TextBox { Left = 20, Top = 80, Width = 400, Text = DefaultDir() };
        var browseBtn = new Button { Text = "浏览…", Left = 430, Top = 77, Width = 80 };
        browseBtn.Click += (s, e) => { var d = new FolderBrowserDialog(); if (d.ShowDialog() == DialogResult.OK) dirBox.Text = d.SelectedPath; };

        prog = new ProgressBar { Left = 20, Top = 118, Width = 500, Height = 20,
                                 Maximum = AppFiles.Length + EXTRA_STEPS, Value = 0 };
        status = new Label { Left = 20, Top = 150, Width = 500, ForeColor = Color.FromArgb(0x1C, 0x2B, 0x4A) };

        installBtn = new Button { Text = "安装", Left = 20, Top = 192, Width = 90 };
        installBtn.Click += (s, e) => Install(dirBox.Text.Trim());
        cancelBtn = new Button { Text = "取消", Left = 120, Top = 192, Width = 90 };
        cancelBtn.Click += (s, e) => Close();

        Controls.AddRange(new Control[] { title, info, dirBox, browseBtn, prog, status, installBtn, cancelBtn });
    }

    static string DefaultDir()
    {
        string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        return Path.Combine(local, "Programs", "CoCa");
    }

    void Ui(Action a) { if (InvokeRequired) Invoke(a); else a(); }

    void Install(string dir)
    {
        installBtn.Enabled = cancelBtn.Enabled = false;
        prog.Value = 0;
        status.Text = "正在安装…";
        Thread t = new Thread(() =>
        {
            try
            {
                DoInstall(dir, (txt, done, total) =>
                    Ui(() => { prog.Maximum = Math.Max(1, total); prog.Value = done; status.Text = txt; }));
                Ui(() => { prog.Value = prog.Maximum; status.Text = "安装成功！"; });
                Thread.Sleep(60);
                Ui(() =>
                {
                    MessageBox.Show("CoCa 安装成功！", "CoCa", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    Close();   // 点确定后自动关闭安装程序
                });
            }
            catch (Exception ex)
            {
                Ui(() =>
                {
                    status.Text = "安装失败：" + ex.Message;
                    MessageBox.Show("安装失败：" + ex.Message, "CoCa", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    installBtn.Enabled = cancelBtn.Enabled = true;
                });
            }
        });
        t.IsBackground = true;
        t.Start();
    }

    static void DoInstall(string dir, Action<string, int, int> report)
    {
        string target = Path.GetFullPath(string.IsNullOrEmpty(dir) ? DefaultDir() : dir.Trim());
        Directory.CreateDirectory(target);
        Assembly asm = Assembly.GetExecutingAssembly();
        int step = 0;
        int total = AppFiles.Length + EXTRA_STEPS;
        foreach (var n in AppFiles)
        {
            using (Stream s = asm.GetManifestResourceStream(n))
            {
                if (s == null) throw new Exception("缺少内嵌资源: " + n);
                using (var fs = File.Create(Path.Combine(target, n))) s.CopyTo(fs);
            }
            step++;
            if (report != null) { report("正在复制 " + n + "（" + step + "/" + AppFiles.Length + "）", step, total); Thread.Sleep(60); }
        }
        string exe = Path.Combine(target, "CoCa.exe");
        if (report != null) report("创建桌面快捷方式…", ++step, total);
        MakeShortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Desktop), "CoCa.lnk"), exe, target);
        if (report != null) report("创建开始菜单快捷方式…", ++step, total);
        string startDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "CoCa");
        Directory.CreateDirectory(startDir);
        MakeShortcut(Path.Combine(startDir, "CoCa.lnk"), exe, target);
        if (report != null) report("注册卸载信息…", ++step, total);
        RegisterUninstall(target, exe);
        if (report != null) report("完成", step, step);
    }

    static void RegisterUninstall(string target, string exe)
    {
        try
        {
            using (var k = Registry.CurrentUser.CreateSubKey(
                @"Software\Microsoft\Windows\CurrentVersion\Uninstall\CoCa"))
            {
                k.SetValue("DisplayName", "CoCa 相机拷卡工具");
                k.SetValue("DisplayVersion", "1.0");
                k.SetValue("Publisher", "CoCa");
                k.SetValue("InstallLocation", target);
                k.SetValue("DisplayIcon", exe);
                k.SetValue("UninstallString", "\"" + Path.Combine(target, "CoCa_Uninstall.exe") + "\"");
                k.SetValue("NoModify", 1);
                k.SetValue("NoRepair", 1);
            }
        }
        catch { }
    }

    static void MakeShortcut(string lnkPath, string target, string workdir)
    {
        try
        {
            Type t = Type.GetTypeFromProgID("WScript.Shell");
            object shell = Activator.CreateInstance(t);
            object lnk = t.InvokeMember("CreateShortcut", System.Reflection.BindingFlags.InvokeMethod,
                                        null, shell, new object[] { lnkPath });
            Type lt = lnk.GetType();
            lt.InvokeMember("TargetPath", System.Reflection.BindingFlags.SetProperty, null, lnk, new object[] { target });
            lt.InvokeMember("WorkingDirectory", System.Reflection.BindingFlags.SetProperty, null, lnk, new object[] { workdir });
            lt.InvokeMember("Save", System.Reflection.BindingFlags.InvokeMethod, null, lnk, null);
        }
        catch { }
    }

    static void ExtractOnly(string dir)
    {
        string target = Path.GetFullPath(dir.Trim());
        Directory.CreateDirectory(target);
        Assembly asm = Assembly.GetExecutingAssembly();
        foreach (var n in AppFiles)
        {
            using (Stream s = asm.GetManifestResourceStream(n))
            {
                if (s == null) throw new Exception("缺少内嵌资源: " + n);
                using (var fs = File.Create(Path.Combine(target, n))) s.CopyTo(fs);
            }
        }
        Console.WriteLine("EXTRACT_OK:" + target);
    }

    [STAThread]
    static void Main(string[] args)
    {
        string dir = null;
        int di = Array.IndexOf(args, "--dir");
        if (di >= 0 && di + 1 < args.Length) dir = args[di + 1];
        if (Array.IndexOf(args, "--extract") >= 0) { ExtractOnly(dir); return; }
        if (Array.IndexOf(args, "--silent") >= 0) { DoInstall(dir, null); return; }
        Application.EnableVisualStyles();
        Application.Run(new SetupForm());
    }
}
