using System.Text.Json;

namespace AlkoCop.Agent.Core;

/// <summary>Переносит данные из локальной очереди на сервер пачками.</summary>
public sealed class OutboxUploader(OutboxQueue queue, ServerClient client, int batchSize = 500)
{
    /// <summary>Отправляет всё, что накопилось. Возвращает число отправленных записей.</summary>
    public async Task<int> DrainAsync(string token, CancellationToken ct)
    {
        var sent = 0;
        while (!ct.IsCancellationRequested)
        {
            var items = queue.Peek(batchSize);
            if (items.Count == 0)
            {
                break;
            }

            var spans = new List<ActivitySpanDto>();
            var events = new List<SystemEventDto>();
            var broken = new List<string>();
            foreach (var item in items)
            {
                try
                {
                    switch (item.Kind)
                    {
                        case OutboxQueue.KindSpan:
                            spans.Add(JsonSerializer.Deserialize<ActivitySpanDto>(item.Payload, AgentJson.Options)!);
                            break;
                        case OutboxQueue.KindEvent:
                            events.Add(JsonSerializer.Deserialize<SystemEventDto>(item.Payload, AgentJson.Options)!);
                            break;
                        default:
                            broken.Add(item.Id);
                            break;
                    }
                }
                catch (JsonException)
                {
                    broken.Add(item.Id);
                }
            }

            if (spans.Count + events.Count > 0)
            {
                await client.UploadActivityAsync(token, new ActivityBatch(spans, events), ct);
            }
            // Сервер подтвердил приём (повторы он отсеивает сам), можно удалять.
            queue.Remove(items.Select(i => i.Id));
            sent += spans.Count + events.Count;
            if (items.Count < batchSize)
            {
                break;
            }
        }
        return sent;
    }
}
