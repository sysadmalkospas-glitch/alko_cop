using System.ComponentModel;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using AlkoCop.Agent.Core;
using ImageMagick;

namespace AlkoCop.Agent.Collector;

internal sealed class ScreenCapture
{
    private const int ThumbnailSize = 32;
    private readonly Dictionary<(int Index, string Device, Rectangle Bounds), byte[]> _previous = [];
    private long _connectionVersion;
    private AgentConfigDto? _profile;

    public IReadOnlyList<ScreenshotFrame> Take(AgentConfigDto config, long connectionVersion, CancellationToken ct)
    {
        if (_profile != config || _connectionVersion != connectionVersion)
        {
            _previous.Clear();
            _profile = config;
            _connectionVersion = connectionVersion;
        }
        var (format, contentType) = config.ScreenshotFormat.ToLowerInvariant() switch
        {
            "webp" => (MagickFormat.WebP, "image/webp"),
            "avif" => (MagickFormat.Avif, "image/avif"),
            "jpeg" => (MagickFormat.Jpeg, "image/jpeg"),
            _ => (MagickFormat.Unknown, ""),
        };
        if (!config.ScreenshotsEnabled || format == MagickFormat.Unknown || !NativeMethods.IsInteractiveDesktop())
        {
            return [];
        }

        var captured = new List<ScreenshotFrame>();
        var screens = Screen.AllScreens.OrderBy(s => s.DeviceName, StringComparer.Ordinal).Take(ScreenshotFrame.MaxMonitor + 1).ToArray();
        var topology = screens.Select((screen, index) => (index, screen.DeviceName, screen.Bounds)).ToHashSet();
        foreach (var removed in _previous.Keys.Where(key => !topology.Contains(key)).ToArray())
        {
            _previous.Remove(removed);
        }
        var takenAt = DateTimeOffset.UtcNow;
        for (var monitor = 0; monitor < screens.Length; monitor++)
        {
            if (ct.IsCancellationRequested || !NativeMethods.IsInteractiveDesktop())
            {
                break;
            }
            var screen = screens[monitor];
            try
            {
                var bounds = screen.Bounds;
                using var bitmap = new Bitmap(bounds.Width, bounds.Height, PixelFormat.Format24bppRgb);
                using (var graphics = Graphics.FromImage(bitmap))
                {
                    graphics.CopyFromScreen(bounds.Location, Point.Empty, bounds.Size, CopyPixelOperation.SourceCopy);
                }
                if (!NativeMethods.IsInteractiveDesktop())
                {
                    break;
                }

                var key = (monitor, screen.DeviceName, bounds);
                var thumbnail = config.ScreenshotSkipUnchanged ? MakeThumbnail(bitmap) : null;
                if (thumbnail is not null && _previous.TryGetValue(key, out var previous)
                    && ScreenshotComparison.IsNearDuplicate(previous, thumbnail))
                {
                    continue;
                }

                var bytes = Encode(bitmap, format, config.ScreenshotQuality, config.ScreenshotMaxWidth);
                var frame = new ScreenshotFrame(Guid.NewGuid(), takenAt, monitor, contentType, bytes);
                if (frame.IsValid())
                {
                    captured.Add(frame);
                    if (thumbnail is not null)
                    {
                        _previous[key] = thumbnail;
                    }
                }
            }
            catch (Exception ex) when (ex is Win32Exception or ExternalException or ArgumentException or MagickException)
            {
                // A display can disappear or become inaccessible mid-capture. Other screens and activity continue.
            }
        }
        return captured;
    }

    private static byte[] MakeThumbnail(Bitmap bitmap)
    {
        using var thumbnail = new Bitmap(ThumbnailSize, ThumbnailSize, PixelFormat.Format24bppRgb);
        using (var graphics = Graphics.FromImage(thumbnail))
        {
            graphics.InterpolationMode = InterpolationMode.HighQualityBilinear;
            graphics.DrawImage(bitmap, new Rectangle(0, 0, ThumbnailSize, ThumbnailSize));
        }
        var bytes = new byte[ThumbnailSize * ThumbnailSize * 3];
        var bits = thumbnail.LockBits(new Rectangle(0, 0, ThumbnailSize, ThumbnailSize), ImageLockMode.ReadOnly, thumbnail.PixelFormat);
        try
        {
            for (var y = 0; y < ThumbnailSize; y++)
            {
                Marshal.Copy(bits.Scan0 + y * bits.Stride, bytes, y * ThumbnailSize * 3, ThumbnailSize * 3);
            }
        }
        finally
        {
            thumbnail.UnlockBits(bits);
        }
        return bytes;
    }

    private static byte[] Encode(Bitmap bitmap, MagickFormat format, int quality, int maxWidth)
    {
        using var source = new MemoryStream();
        bitmap.Save(source, ImageFormat.Bmp);
        source.Position = 0;
        using var image = new MagickImage(source);
        if (maxWidth > 0 && (uint)maxWidth < image.Width)
        {
            image.Resize((uint)maxWidth, 0);
        }
        image.Quality = (uint)Math.Clamp(quality, 1, 100);
        if (format == MagickFormat.Avif)
        {
            image.Settings.SetDefine(MagickFormat.Heic, "speed", "8");
        }
        return image.ToByteArray(format);
    }
}
