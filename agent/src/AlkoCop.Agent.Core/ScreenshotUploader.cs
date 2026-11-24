using System.Diagnostics;
using System.Net;

namespace AlkoCop.Agent.Core;

public sealed class ScreenshotUploader(ScreenshotQueue queue, ServerClient client)
{
    public async Task<int> DrainAsync(string token, TimeSpan timeBudget, CancellationToken ct)
    {
        var started = Stopwatch.StartNew();
        var sent = 0;
        while (started.Elapsed < timeBudget && !ct.IsCancellationRequested && queue.Peek() is { } item)
        {
            try
            {
                await client.UploadScreenshotAsync(token, item, ct);
                sent++;
            }
            catch (HttpRequestException ex) when (ex.StatusCode is HttpStatusCode.RequestEntityTooLarge
                or HttpStatusCode.UnsupportedMediaType or HttpStatusCode.UnprocessableContent)
            {
                // Only discard frames rejected for their own contents; transient failures keep the file.
            }
            queue.Remove(item.Frame.Id);
        }
        return sent;
    }
}
