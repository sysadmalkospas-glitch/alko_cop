namespace AlkoCop.Agent.Core;

/// <summary>Compares downsampled RGB thumbnails, tolerating minor cursor or clock changes.</summary>
public static class ScreenshotComparison
{
    public static bool IsNearDuplicate(ReadOnlySpan<byte> previous, ReadOnlySpan<byte> current)
    {
        if (previous.Length != current.Length || current.Length == 0 || current.Length % 3 != 0)
        {
            return false;
        }

        const int channelTolerance = 16;
        var pixels = current.Length / 3;
        var changed = 0;
        for (var i = 0; i < current.Length; i += 3)
        {
            if (Math.Abs(previous[i] - current[i]) > channelTolerance
                || Math.Abs(previous[i + 1] - current[i + 1]) > channelTolerance
                || Math.Abs(previous[i + 2] - current[i + 2]) > channelTolerance)
            {
                // At most 1% of thumbnail pixels may differ substantially.
                if (++changed > pixels / 100)
                {
                    return false;
                }
            }
        }
        return true;
    }
}
