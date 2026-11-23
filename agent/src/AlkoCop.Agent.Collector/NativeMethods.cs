using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

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

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static partial bool GetNamedPipeServerSessionId(SafePipeHandle pipe, out uint sessionId);

    [LibraryImport("user32.dll", SetLastError = true)]
    private static partial IntPtr OpenInputDesktop(uint flags, [MarshalAs(UnmanagedType.Bool)] bool inherit, uint access);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool CloseDesktop(IntPtr desktop);

    [DllImport("user32.dll", EntryPoint = "GetUserObjectInformationW", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetUserObjectInformation(IntPtr handle, int index, StringBuilder info, uint size, out uint needed);

    [LibraryImport("wtsapi32.dll", EntryPoint = "WTSQuerySessionInformationW", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool WTSQuerySessionInformation(IntPtr server, uint sessionId, int infoClass, out IntPtr buffer, out uint bytes);

    [LibraryImport("wtsapi32.dll")]
    private static partial void WTSFreeMemory(IntPtr buffer);

    internal static bool IsInteractiveDesktop()
    {
        const uint currentSession = uint.MaxValue;
        const int connectState = 8;
        const int active = 0;
        if (!WTSQuerySessionInformation(IntPtr.Zero, currentSession, connectState, out var buffer, out var bytes))
        {
            return false;
        }
        try
        {
            if (buffer == IntPtr.Zero || bytes < sizeof(int) || Marshal.ReadInt32(buffer) != active)
            {
                return false;
            }
        }
        finally
        {
            WTSFreeMemory(buffer);
        }

        const uint desktopReadObjects = 1;
        const int objectName = 2;
        var desktop = OpenInputDesktop(0, false, desktopReadObjects);
        if (desktop == IntPtr.Zero)
        {
            return false;
        }
        try
        {
            var name = new StringBuilder(64);
            return GetUserObjectInformation(desktop, objectName, name, (uint)(name.Capacity * sizeof(char)), out _)
                && string.Equals(name.ToString(), "Default", StringComparison.OrdinalIgnoreCase);
        }
        finally
        {
            CloseDesktop(desktop);
        }
    }

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
