using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Threading;

// Observe the installed app from its disposable NSIS lifecycle check.
public static class InstalledWorkspace
{
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr FindWindowEx(IntPtr parent, IntPtr after, string type, string title);
    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")]
    private static extern bool IsIconic(IntPtr window);
    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool PostMessageW(IntPtr window, uint message, UIntPtr wParam, IntPtr lParam);

    private static void Wait(Func<bool> ready, int seconds, string failure)
    {
        var timer = Stopwatch.StartNew();
        while (!ready())
        {
            if (timer.Elapsed.TotalSeconds >= seconds) throw new TimeoutException(failure);
            Thread.Sleep(50);
        }
    }

    public static IntPtr Find(uint pid, int seconds)
    {
        IntPtr window = IntPtr.Zero;
        Wait(() => {
            while ((window = FindWindowEx(IntPtr.Zero, window, null, "Yap")) != IntPtr.Zero)
            {
                GetWindowThreadProcessId(window, out uint owner);
                if (owner == pid && IsWindowVisible(window)) return true;
            }
            return false;
        }, seconds, "The installed process did not show its main window.");
        return window;
    }

    public static void Minimize(IntPtr window, int seconds)
    {
        const uint WM_SYSCOMMAND = 0x0112, SC_MINIMIZE = 0xF020;
        if (!PostMessageW(window, WM_SYSCOMMAND, new UIntPtr(SC_MINIMIZE), IntPtr.Zero))
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        Wait(() => IsIconic(window), seconds, "The original window did not minimize.");
    }

    public static void CloseToTray(IntPtr window, int seconds)
    {
        const uint WM_CLOSE = 0x0010;
        if (!PostMessageW(window, WM_CLOSE, UIntPtr.Zero, IntPtr.Zero))
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        Wait(() => !IsWindowVisible(window), seconds, "Closing the original window did not hide it.");
    }

    public static void WaitForRestore(IntPtr window, uint pid, int seconds)
    {
        Wait(() => {
            GetWindowThreadProcessId(window, out uint owner);
            return owner == pid && IsWindowVisible(window) && !IsIconic(window);
        }, seconds, "Second launch did not restore the original process and window.");
    }
}
