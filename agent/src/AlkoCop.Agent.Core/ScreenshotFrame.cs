namespace AlkoCop.Agent.Core;

/// <summary>One monitor's encoded image. The service supplies the login separately.</summary>
public sealed record ScreenshotFrame(Guid Id, DateTimeOffset TakenAt, int Monitor, string ContentType, byte[] Data)
{
    // Matches the server's default single-image limit. Allow room for Base64 and JSON metadata on the pipe.
    public const int MaxBytes = 5 * 1024 * 1024;
    public const int MaxMonitor = 16;
    public const int MaxPipeLineLength = ((MaxBytes + 2) / 3 * 4) + 1024;

    public bool IsValid() => Id != Guid.Empty && TakenAt != default && Monitor is >= 0 and <= MaxMonitor
        && Data is { Length: > 0 and <= MaxBytes } && HasImageHeader();

    private bool HasImageHeader()
    {
        ReadOnlySpan<byte> bytes = Data;
        return ContentType switch
        {
            "image/jpeg" => bytes is [0xFF, 0xD8, 0xFF, ..],
            "image/webp" => bytes.Length >= 12 && bytes.StartsWith("RIFF"u8) && bytes[8..].StartsWith("WEBP"u8),
            "image/avif" => bytes.Length >= 12 && bytes[4..].StartsWith("ftypavif"u8),
            _ => false,
        };
    }
}
