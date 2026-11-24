using System.Text;

namespace AlkoCop.Agent.Service;

/// <summary>Reads JSON lines with a size ceiling before allocating a complete message.</summary>
internal sealed class BoundedPipeReader(StreamReader reader, int maxLength)
{
    private readonly char[] _buffer = new char[8192];
    private int _start;
    private int _end;

    public async Task<string?> ReadLineAsync(CancellationToken ct)
    {
        var line = new StringBuilder();
        var oversized = false;
        while (true)
        {
            if (_start == _end)
            {
                _start = 0;
                _end = await reader.ReadAsync(_buffer.AsMemory(), ct);
                if (_end == 0)
                {
                    return null;
                }
            }

            var newline = Array.IndexOf(_buffer, '\n', _start, _end - _start);
            var count = (newline >= 0 ? newline : _end) - _start;
            oversized |= line.Length + count > maxLength;
            if (!oversized)
            {
                line.Append(_buffer, _start, count);
            }
            _start += count;
            if (newline >= 0)
            {
                _start++;
                return oversized ? string.Empty : line.ToString();
            }
        }
    }
}
