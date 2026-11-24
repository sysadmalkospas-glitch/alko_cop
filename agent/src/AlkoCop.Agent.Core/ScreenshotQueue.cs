using System.Globalization;
using System.Text;

namespace AlkoCop.Agent.Core;

public sealed record QueuedScreenshot(string Login, ScreenshotFrame Frame);

/// <summary>Durable, size-limited FIFO for images, independent of the activity outbox.</summary>
public sealed class ScreenshotQueue
{
    public const long DefaultCapacityBytes = 2L * 1024 * 1024 * 1024;

    private const int DiskBlockBytes = 4096;
    private const int MaxMetadataBytes = 2048;
    private readonly string _directory;
    private readonly long _capacityBytes;
    private readonly Lock _lock = new();
    private readonly SortedDictionary<long, Entry> _entries = [];
    private readonly Dictionary<Guid, long> _sequenceById = [];
    private long _sequence;
    private long _usedBytes;

    public ScreenshotQueue(string directory, long capacityBytes = DefaultCapacityBytes)
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(capacityBytes);
        _directory = directory;
        _capacityBytes = capacityBytes;
        Directory.CreateDirectory(directory);
        foreach (var path in Directory.EnumerateFiles(directory, "*.tmp"))
        {
            File.Delete(path);
        }
        foreach (var entry in Directory.EnumerateFiles(directory, "*.frame").Select(path => new FileInfo(path)))
        {
            var name = Path.GetFileNameWithoutExtension(entry.Name);
            if (name.Length != 52 || name[19] != '-' || entry.Length > ScreenshotFrame.MaxBytes + MaxMetadataBytes
                || !long.TryParse(name.AsSpan(0, 19), NumberStyles.None, CultureInfo.InvariantCulture, out var sequence)
                || !Guid.TryParseExact(name.AsSpan(20), "N", out var id))
            {
                File.Delete(entry.FullName);
                continue;
            }
            if (_entries.ContainsKey(sequence) || _sequenceById.ContainsKey(id))
            {
                File.Delete(entry.FullName);
                continue;
            }
            Add(new Entry(id, sequence, entry.FullName, DiskBytes(entry.Length)));
            _sequence = Math.Max(_sequence, sequence);
        }
        MakeSpace(0);
    }

    public bool Enqueue(string login, ScreenshotFrame frame)
    {
        if (string.IsNullOrEmpty(login) || login.Length > 300 || !frame.IsValid())
        {
            return false;
        }

        lock (_lock)
        {
            if (_sequenceById.ContainsKey(frame.Id))
            {
                return true;
            }

            // Account for the actual binary header plus the filesystem blocks occupied by the file.
            using var header = new MemoryStream();
            using (var writer = new BinaryWriter(header, Encoding.UTF8, leaveOpen: true))
            {
                writer.Write(login);
                writer.Write(frame.TakenAt.UtcTicks);
                writer.Write(frame.Monitor);
                writer.Write(frame.ContentType);
            }
            var size = DiskBytes(header.Length + frame.Data.Length);
            if (size > _capacityBytes)
            {
                return false;
            }

            MakeSpace(size);
            var sequence = checked(++_sequence);
            var name = sequence.ToString("D19", CultureInfo.InvariantCulture) + "-" + frame.Id.ToString("N");
            var path = Path.Combine(_directory, name + ".frame");
            var temp = Path.Combine(_directory, name + ".tmp");
            try
            {
                using (var stream = new FileStream(temp, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    header.WriteTo(stream);
                    stream.Write(frame.Data);
                    stream.Flush(flushToDisk: true);
                }
                File.Move(temp, path);
                Add(new Entry(frame.Id, sequence, path, size));
                return true;
            }
            finally
            {
                File.Delete(temp);
            }
        }
    }

    public QueuedScreenshot? Peek()
    {
        lock (_lock)
        {
            while (_entries.Count > 0)
            {
                var entry = _entries.First().Value;
                try
                {
                    using var stream = File.OpenRead(entry.Path);
                    using var reader = new BinaryReader(stream, Encoding.UTF8);
                    var login = reader.ReadString();
                    var takenAt = new DateTimeOffset(reader.ReadInt64(), TimeSpan.Zero);
                    var monitor = reader.ReadInt32();
                    var contentType = reader.ReadString();
                    var remaining = stream.Length - stream.Position;
                    if (remaining is > 0 and <= ScreenshotFrame.MaxBytes && login.Length is > 0 and <= 300)
                    {
                        var frame = new ScreenshotFrame(entry.Id, takenAt, monitor, contentType, reader.ReadBytes((int)remaining));
                        if (frame.Data.Length == remaining && frame.IsValid())
                        {
                            return new QueuedScreenshot(login, frame);
                        }
                    }
                }
                catch (Exception ex) when (ex is EndOfStreamException or FileNotFoundException or FormatException or ArgumentOutOfRangeException)
                {
                    // A damaged or missing frame must not block all later uploads.
                }
                Delete(entry);
            }
            return null;
        }
    }

    public void Remove(Guid id)
    {
        lock (_lock)
        {
            if (_sequenceById.TryGetValue(id, out var sequence))
            {
                Delete(_entries[sequence]);
            }
        }
    }

    private static long DiskBytes(long length) => (length + DiskBlockBytes - 1) / DiskBlockBytes * DiskBlockBytes;

    private void MakeSpace(long size)
    {
        while (_usedBytes > _capacityBytes - size)
        {
            Delete(_entries.First().Value);
        }
    }

    private void Delete(Entry entry)
    {
        File.Delete(entry.Path);
        _entries.Remove(entry.Sequence);
        _sequenceById.Remove(entry.Id);
        _usedBytes -= entry.Size;
    }

    private void Add(Entry entry)
    {
        _entries.Add(entry.Sequence, entry);
        _sequenceById.Add(entry.Id, entry.Sequence);
        _usedBytes += entry.Size;
    }

    private sealed record Entry(Guid Id, long Sequence, string Path, long Size);
}
