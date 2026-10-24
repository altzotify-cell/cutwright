using System;
using System.Collections.Generic;
using System.Text;
using System.Runtime.InteropServices;

public static class NativeInput
{
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, int dx, int dy, uint data, IntPtr extra);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool ScreenToClient(IntPtr hWnd, ref POINT p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, IntPtr pid);
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetActiveWindow(IntPtr hWnd);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT { public int X; public int Y; }

    public const uint WM_CLOSE = 0x0010;
    public const uint WM_LBUTTONDOWN = 0x0201;
    public const uint WM_LBUTTONUP = 0x0202;
    private const uint LEFTDOWN = 0x0002;
    private const uint LEFTUP = 0x0004;
    private const int MK_LBUTTON = 0x0001;

    public static void Click(int x, int y)
    {
        SetCursorPos(x, y);
        System.Threading.Thread.Sleep(150);
        mouse_event(LEFTDOWN, 0, 0, 0, IntPtr.Zero);
        System.Threading.Thread.Sleep(70);
        mouse_event(LEFTUP, 0, 0, 0, IntPtr.Zero);
    }

    public static void ClickRect(double left, double top, double width, double height)
    {
        Click((int)(left + width / 2.0), (int)(top + height / 2.0));
    }

    /// Defeats the Windows foreground lock so SendKeys/mouse actually land.
    public static void ForceForeground(int hwnd)
    {
        IntPtr h = new IntPtr(hwnd);
        uint fgThread = GetWindowThreadProcessId(GetForegroundWindow(), IntPtr.Zero);
        uint myThread = GetCurrentThreadId();
        bool attached = false;
        if (fgThread != myThread && fgThread != 0)
        {
            attached = AttachThreadInput(myThread, fgThread, true);
        }
        BringWindowToTop(h);
        SetForegroundWindow(h);
        SetActiveWindow(h);
        if (attached) { AttachThreadInput(myThread, fgThread, false); }
    }

    /// Clicks a window by POSTING the messages, so it works even when the
    /// target is not foreground. Coordinates are screen coordinates.
    public static bool PostClick(int hwnd, int screenX, int screenY)
    {
        IntPtr h = new IntPtr(hwnd);
        POINT p = new POINT();
        p.X = screenX; p.Y = screenY;
        ScreenToClient(h, ref p);
        IntPtr lp = (IntPtr)((p.Y << 16) | (p.X & 0xFFFF));
        PostMessage(h, WM_LBUTTONDOWN, (IntPtr)MK_LBUTTON, lp);
        System.Threading.Thread.Sleep(90);
        PostMessage(h, WM_LBUTTONUP, IntPtr.Zero, lp);
        return true;
    }

    public static bool CloseWindow(int hwnd)
    {
        return PostMessage(new IntPtr(hwnd), WM_CLOSE, IntPtr.Zero, IntPtr.Zero);
    }

    [DllImport("user32.dll")] private static extern void keybd_event(byte vk, byte scan, uint flags, IntPtr extra);

    private const uint KEYUP = 0x0002;
    public const byte VK_TAB = 0x09;
    public const byte VK_RETURN = 0x0D;
    public const byte VK_ESCAPE = 0x1B;

    /// Presses and releases a virtual key on the shared input queue. Unlike
    /// PostMessage(WM_KEYDOWN) this works against custom-drawn windows that do
    /// not pump posted keys, and unlike SendKeys it needs no managed dependency.
    public static void Key(byte vk)
    {
        keybd_event(vk, 0, 0, IntPtr.Zero);
        System.Threading.Thread.Sleep(60);
        keybd_event(vk, 0, KEYUP, IntPtr.Zero);
    }
}
