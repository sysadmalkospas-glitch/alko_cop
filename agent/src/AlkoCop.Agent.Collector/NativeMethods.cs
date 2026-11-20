using System.Runtime.InteropServices;
using System.Text;

namespace AlkoCop.Agent.Collector;

internal static partial class NativeMethods
{
    [StructLayout(LayoutKind.Sequential)]
    internal struct LASTINPUTINFO
    {
        public uint cbSize;
        public uint dwTime;
    }

    [LibraryImport("user32.dll")]
    internal static partial IntPtr GetForegroundWindow();

    [LibraryImport("user32.dll", EntryPoint = "GetWindowTextLengthW", SetLastError = true)]
    internal static partial int GetWindowTextLength(IntPtr hWnd);

    [DllImport("user32.dll", EntryPoint = "GetWindowTextW", CharSet = CharSet.Unicode, SetLastError = true)]
    internal static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int maxCount);

    [LibraryImport("user32.dll", SetLastError = true)]
    internal static partial uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static partial bool GetLastInputInfo(ref LASTINPUTINFO info);

    [LibraryImport("kernel32.dll")]
    internal static partial uint GetTickCount();

    internal static string? GetWindowTitle(IntPtr hWnd)
    {
        var length = GetWindowTextLength(hWnd);
        if (length <= 0)
        {
            return null;
        }
        var sb = new StringBuilder(length + 1);
        return GetWindowText(hWnd, sb, sb.Capacity) > 0 ? sb.ToString() : null;
    }

    /// <summary>Сколько прошло с последнего нажатия клавиши или движения мыши в этой сессии.</summary>
    internal static TimeSpan GetIdleTime()
    {
        var info = new LASTINPUTINFO { cbSize = (uint)Marshal.SizeOf<LASTINPUTINFO>() };
        if (!GetLastInputInfo(ref info))
        {
            return TimeSpan.Zero;
        }
        // Беззнаковая разность корректна и при переполнении счётчика (49,7 суток).
        return TimeSpan.FromMilliseconds(unchecked(GetTickCount() - info.dwTime));
    }
}
