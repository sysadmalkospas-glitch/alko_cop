using AlkoCop.Agent.Core;

namespace AlkoCop.Agent.Core.Tests;

public class ActivityTrackerTests
{
    private static readonly DateTimeOffset T0 = new(2026, 11, 20, 7, 0, 0, TimeSpan.Zero);
    private int _ids;

    private ActivityTracker NewTracker() => new(
        idleThreshold: TimeSpan.FromMinutes(5),
        maxSpanLength: TimeSpan.FromMinutes(1),
        maxSampleGap: TimeSpan.FromMinutes(2),
        newId: () => $"id{++_ids}");

    private static WindowSample At(int seconds, string? title = "МИС", double idleSec = 0) =>
        new(T0.AddSeconds(seconds), "CLINIC\\ivanova", 2, "mis.exe", title, null, TimeSpan.FromSeconds(idleSec));

    [Fact]
    public void SameWindow_ProducesNothingUntilChange()
    {
        var t = NewTracker();
        for (var s = 0; s < 30; s++)
        {
            Assert.Empty(t.Add(At(s)));
        }
    }

    [Fact]
    public void WindowChange_ClosesSpanAtChange()
    {
        var t = NewTracker();
        t.Add(At(0));
        t.Add(At(10));
        var closed = Assert.Single(t.Add(At(20, title: "Excel")));
        Assert.Equal(T0, closed.StartedAt);
        Assert.Equal(T0.AddSeconds(20), closed.EndedAt);
        Assert.Equal("МИС", closed.WindowTitle);
        Assert.False(closed.IsIdle);
    }

    [Fact]
    public void LongSpan_IsSplitByMaxLength()
    {
        var t = NewTracker();
        t.Add(At(0));
        var closed = Assert.Single(t.Add(At(60)));
        Assert.Equal(TimeSpan.FromMinutes(1), closed.EndedAt - closed.StartedAt);
        var next = Assert.Single(t.Flush(T0.AddSeconds(90)));
        Assert.Equal(T0.AddSeconds(60), next.StartedAt);
        Assert.NotEqual(closed.Id, next.Id);
    }

    [Fact]
    public void Idle_IsBackdatedToLastInput_EvenAcrossMaxLength()
    {
        var t = NewTracker();
        var closed = new List<ActivitySpanDto>();
        // Работа до 30 с, затем ввода нет: замеры раз в секунду.
        for (var s = 0; s <= 30; s++)
        {
            closed.AddRange(t.Add(At(s)));
        }
        for (var s = 31; s <= 340; s++)
        {
            closed.AddRange(t.Add(At(s, idleSec: s - 30)));
        }
        closed.AddRange(t.Add(At(341)));

        // Отрезки без простоя заканчиваются в момент последнего ввода (30 с).
        var active = closed.Where(c => !c.IsIdle).ToList();
        Assert.Equal(T0.AddSeconds(30), active.Max(c => c.EndedAt));

        var idle = Assert.Single(closed, c => c.IsIdle);
        Assert.Null(idle.WindowTitle);
        Assert.Equal(T0.AddSeconds(30), idle.StartedAt);
        Assert.Equal(T0.AddSeconds(341), idle.EndedAt);
    }

    [Fact]
    public void ShortPause_StaysActive()
    {
        var t = NewTracker();
        var closed = new List<ActivitySpanDto>();
        for (var s = 0; s <= 200; s++)
        {
            // Пауза 2 минуты в середине, порог простоя 5 минут.
            var idle = s is > 50 and <= 170 ? s - 50 : 0;
            closed.AddRange(t.Add(At(s, idleSec: idle)));
        }
        closed.AddRange(t.Flush(T0.AddSeconds(200)));
        Assert.All(closed, c => Assert.False(c.IsIdle));
        Assert.Equal(TimeSpan.FromSeconds(200), TimeSpan.FromTicks(closed.Sum(c => (c.EndedAt - c.StartedAt).Ticks)));
    }

    [Fact]
    public void SampleGap_ClosesAtLastSeen()
    {
        var t = NewTracker();
        t.Add(At(0));
        t.Add(At(20));
        // Компьютер спал 1 час.
        var closed = Assert.Single(t.Add(At(3620)));
        Assert.Equal(T0.AddSeconds(20), closed.EndedAt);
        Assert.Empty(t.Add(At(3621)));
    }

    [Fact]
    public void ZeroLengthSpans_AreDropped()
    {
        var t = NewTracker();
        t.Add(At(0));
        Assert.Empty(t.Flush(T0));
    }
}
