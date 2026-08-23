// uninstall.cs - CoCa 卸载程序：删除已安装文件、桌面/开始菜单快捷方式、注册表卸载项，并自删。
// 编译：
//   csc /target:winexe /out:CoCa_Uninstall.exe /win32icon:icon.ico /r:System.Windows.Forms.dll uninstall.cs
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Windows.Forms;
using Microsoft.Win32;

public class UninstallForm : Form
{
    Label status;
    Button yesBtn, noBtn;
    public UninstallForm()
    {
        Text = "CoCa 卸载";
        ClientSize = new Size(440, 180);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false; MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;

        var msg = new Label { Text = "确定要卸载 CoCa 吗？", Left = 20, Top = 26,
                              Font = new Font("Microsoft YaHei UI", 11),
                              AutoSize = true };
        yesBtn = new Button { Text = "确认卸载", Left = 20, Top = 76, Width = 100 };
        yesBtn.Click += (s, e) =>
        {
            yesBtn.Enabled = noBtn.Enabled = false;
            status.Text = "正在卸载…";
            DoUninstall();
            status.Text = "正在清理残留…";
            MessageBox.Show("CoCa 已成功卸载！", "CoCa 卸载", MessageBoxButtons.OK, MessageBoxIcon.Information);
            Close();
        };
        noBtn = new Button { Text = "取消", Left = 130, Top = 80, Width = 90 };
        noBtn.Click += (s, e) => Close();
        status = new Label { Left = 20, Top = 122, Width = 400, ForeColor = Color.FromArgb(0x1C, 0x2B, 0x4A) };
        Controls.AddRange(new Control[] { msg, yesBtn, noBtn, status });
    }

    static void DeleteFile(string p) { try { if (File.Exists(p)) File.Delete(p); } catch { } }
    static void DeleteDir(string p) { try { if (Directory.Exists(p)) Directory.Delete(p, true); } catch { } }

    static void DoUninstall()
    {
        string dir = Path.GetDirectoryName(Application.ExecutablePath);
        string exeName = Path.GetFileName(Application.ExecutablePath);

        // 1) 删除桌面 + 开始菜单快捷方式
        DeleteFile(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Desktop), "CoCa.lnk"));
        DeleteDir(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "CoCa"));

        // 2) 删除安装目录里的文件（保留正在运行的卸载程序本身）
        try
        {
            foreach (var f in Directory.GetFiles(dir))
                if (Path.GetFileName(f) != exeName) { try { File.Delete(f); } catch { } }
            foreach (var d in Directory.GetDirectories(dir))
                try { Directory.Delete(d, true); } catch { }
        }
        catch { }

        // 3) 删除注册表卸载项
        try { Registry.CurrentUser.DeleteSubKeyTree(
            @"Software\Microsoft\Windows\CurrentVersion\Uninstall\CoCa", false); } catch { }

        // 4) 延迟删除整个目录（含卸载程序自身）
        try
        {
            Process.Start(new ProcessStartInfo("cmd.exe",
                "/c ping -n 3 127.0.0.1 >nul & rd /s /q \"" + dir + "\"")
            { CreateNoWindow = true, UseShellExecute = false });
        }
        catch { }
    }

    [STAThread]
    static void Main(string[] args)
    {
        if (Array.IndexOf(args, "--silent") >= 0) { DoUninstall(); return; }
        Application.EnableVisualStyles();
        Application.Run(new UninstallForm());
    }
}
