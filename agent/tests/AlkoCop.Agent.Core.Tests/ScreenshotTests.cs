using System.Net;
using AlkoCop.Agent.Core;

namespace AlkoCop.Agent.Core.Tests;

public sealed class ScreenshotTests : IDisposable
{
    private readonly string _dir = Path.Combine(Path.GetTempPath(), "alkocop-frames-" + Guid.NewGuid().ToString("N"));
    private const string Login = @"OFFICE\employee";

    [Fact]
    public void Comparison_IgnoresSmallChanges_ButDetectsChangedAreas()
    {
        var before = new byte[32 * 32 * 3];
        var after = (byte[])before.Clone();
        Assert.True(ScreenshotComparison.IsNearDuplicate(before, after));
        after[1] = 255;
        Assert.True(ScreenshotComparison.IsNearDuplicate(before, after));
        Array.Fill(after, (byte)255, 0, 12 * 3);
        Assert.False(ScreenshotComparison.IsNearDuplicate(before, after));
        Assert.False(ScreenshotComparison.IsNearDuplicate(before, []));
    }

    [Fact]
    public void Schedule_RespondsToProcessAndLiveProfileChanges()
    {
        var schedule = new ScreenshotSchedule();
        var config = AgentConfigDto.Default;
        Assert.False(schedule.IsDue(null, "first.exe", TimeSpan.Zero));
        Assert.True(schedule.IsDue(config, "first.exe", TimeSpan.Zero));
        Assert.False(schedule.IsDue(config, "FIRST.exe", TimeSpan.FromSeconds(1)));
        Assert.True(schedule.IsDue(config, "second.exe", TimeSpan.FromSeconds(2)));
        Assert.False(schedule.IsDue(config, "second.exe", TimeSpan.FromSeconds(6)));
        Assert.True(schedule.IsDue(config, "second.exe", TimeSpan.FromSeconds(7)));
        Assert.True(schedule.IsDue(config with { ScreenshotFormat = "avif", ScreenshotQuality = 45 }, "second.exe", TimeSpan.FromSeconds(8)));
        Assert.False(schedule.IsDue(config with { ScreenshotsEnabled = false }, "second.exe", TimeSpan.FromSeconds(9)));
        Assert.True(schedule.IsDue(config, "second.exe", TimeSpan.FromSeconds(10)));
    }

    [Fact]
    public void FrameRoundTripsWithoutCollectorSuppliedLogin()
    {
        var frame = Frame();
        var line = new PipeMessage(PipeMessage.TypeScreenshot, Frame: frame).ToLine();
        var parsed = Assert.IsType<ScreenshotFrame>(PipeMessage.FromLine(line)?.Frame);
        Assert.Equal(frame.Id, parsed.Id);
        Assert.Equal(frame.Data, parsed.Data);
        Assert.True(parsed.IsValid());
        Assert.DoesNotContain("login", line);
        Assert.False((parsed with { ContentType = "image/webp" }).IsValid());
        Assert.False((parsed with { Monitor = ScreenshotFrame.MaxMonitor + 1 }).IsValid());
    }

    [Fact]
    public void MaximumSizedFrame_FitsThePipeLineLimit()
    {
        var frame = Frame(ScreenshotFrame.MaxBytes);
        Array.Fill(frame.Data, byte.MaxValue, 3, frame.Data.Length - 3);
        var line = new PipeMessage(PipeMessage.TypeScreenshot, Frame: frame).ToLine();
        Assert.InRange(line.Length, 0, ScreenshotFrame.MaxPipeLineLength);
    }

    [Fact]
    public void Queue_KeepsFrameAcrossRestart_AndEvictsOnlyOldest()
    {
        const int capacity = 8192;
        var first = Frame();
        var second = Frame();
        var third = Frame();
        var queue = new ScreenshotQueue(_dir, capacity);

        Assert.True(queue.Enqueue(Login, first));
        Assert.True(queue.Enqueue(Login, first));
        Assert.True(queue.Enqueue(Login, second));
        Assert.Equal(first.Id, queue.Peek()!.Frame.Id);
        Assert.True(queue.Enqueue(Login, third));

        queue = new ScreenshotQueue(_dir, capacity);
        var stored = queue.Peek()!;
        Assert.Equal(Login, stored.Login);
        Assert.Equal(second.Id, stored.Frame.Id);
        Assert.Equal(second.TakenAt, stored.Frame.TakenAt);
        Assert.Equal(second.Data, stored.Frame.Data);
        queue.Remove(second.Id);
        Assert.Equal(third.Id, queue.Peek()!.Frame.Id);
        queue.Remove(third.Id);
        Assert.Null(queue.Peek());
    }

    [Fact]
    public void Queue_LeavesExistingFrameWhenNewFrameCannotFit()
    {
        var queue = new ScreenshotQueue(_dir, capacityBytes: 4096);
        var small = Frame();
        Assert.True(queue.Enqueue(Login, small));
        Assert.False(queue.Enqueue(Login, Frame(4096)));
        Assert.Equal(small.Id, queue.Peek()!.Frame.Id);
    }

    [Fact]
    public async Task Uploader_RetriesTransientFailuresWithSameId_AndDiscardsRejectedFrame()
    {
        var queue = new ScreenshotQueue(_dir);
        var frame = Frame();
        var rejected = Frame();
        Assert.True(queue.Enqueue(Login, frame));
        Assert.True(queue.Enqueue(Login, rejected));

        using var handler = new MultipartHandler(HttpStatusCode.BadGateway, HttpStatusCode.OK, HttpStatusCode.RequestEntityTooLarge);
        using var http = new HttpClient(handler) { BaseAddress = new Uri("https://server/") };
        var uploader = new ScreenshotUploader(queue, new ServerClient(http));
        await Assert.ThrowsAsync<HttpRequestException>(() => uploader.DrainAsync("token", TimeSpan.FromSeconds(5), CancellationToken.None));
        Assert.Equal(frame.Id, queue.Peek()!.Frame.Id);

        Assert.Equal(1, await uploader.DrainAsync("token", TimeSpan.FromSeconds(5), CancellationToken.None));
        Assert.Null(queue.Peek());
        Assert.Equal([frame.Id.ToString("N"), frame.Id.ToString("N"), rejected.Id.ToString("N")], handler.Ids);
    }

    private static ScreenshotFrame Frame(int size = 100)
    {
        var jpeg = new byte[size];
        byte[] signature = [0xFF, 0xD8, 0xFF];
        signature.CopyTo(jpeg, 0);
        return new ScreenshotFrame(Guid.NewGuid(), DateTimeOffset.UnixEpoch.AddSeconds(1), 1, "image/jpeg", jpeg);
    }

    public void Dispose()
    {
        if (Directory.Exists(_dir))
        {
            Directory.Delete(_dir, recursive: true);
        }
    }

    private sealed class MultipartHandler(params HttpStatusCode[] statuses) : HttpMessageHandler
    {
        public List<string> Ids { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            Assert.Equal(HttpMethod.Post, request.Method);
            Assert.Equal("/api/agent/v1/screenshots", request.RequestUri!.AbsolutePath);
            Assert.Equal("Bearer token", request.Headers.Authorization?.ToString());
            var form = Assert.IsType<MultipartFormDataContent>(request.Content).ToDictionary(part => part.Headers.ContentDisposition!.Name!.Trim('"'));
            Ids.Add(await form["id"].ReadAsStringAsync(ct));
            Assert.Equal(Login, await form["login"].ReadAsStringAsync(ct));
            Assert.Equal("1", await form["monitor"].ReadAsStringAsync(ct));
            Assert.StartsWith("1970-01-01T00:00:01", await form["taken_at"].ReadAsStringAsync(ct));
            Assert.Equal("image/jpeg", form["file"].Headers.ContentType?.MediaType);
            Assert.Equal(100, (await form["file"].ReadAsByteArrayAsync(ct)).Length);
            return new HttpResponseMessage(statuses[Ids.Count - 1]);
        }
    }
}
