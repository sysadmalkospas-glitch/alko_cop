using Microsoft.Data.Sqlite;

namespace AlkoCop.Agent.Core;

public sealed record OutboxItem(string Id, string Kind, string Payload);

/// <summary>
/// Локальная очередь на отправку (SQLite). Данные лежат в ней, пока сервер
/// не подтвердит приём, поэтому обрыв VPN или выключение ПК ничего не теряют.
/// </summary>
public sealed class OutboxQueue : IDisposable
{
    public const string KindSpan = "span";
    public const string KindEvent = "event";

    private readonly SqliteConnection _db;
    private readonly Lock _lock = new();

    public OutboxQueue(string databasePath)
    {
        var dir = Path.GetDirectoryName(Path.GetFullPath(databasePath));
        if (!string.IsNullOrEmpty(dir))
        {
            Directory.CreateDirectory(dir);
        }
        _db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = databasePath }.ToString());
        _db.Open();
        Execute("PRAGMA journal_mode=WAL;");
        Execute("""
            CREATE TABLE IF NOT EXISTS outbox (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            """);
    }

    public void Enqueue(string kind, string id, string payload)
    {
        lock (_lock)
        {
            using var cmd = _db.CreateCommand();
            cmd.CommandText = "INSERT OR IGNORE INTO outbox (id, kind, payload) VALUES ($id, $kind, $payload);";
            cmd.Parameters.AddWithValue("$id", id);
            cmd.Parameters.AddWithValue("$kind", kind);
            cmd.Parameters.AddWithValue("$payload", payload);
            cmd.ExecuteNonQuery();
        }
    }

    public IReadOnlyList<OutboxItem> Peek(int max)
    {
        lock (_lock)
        {
            using var cmd = _db.CreateCommand();
            cmd.CommandText = "SELECT id, kind, payload FROM outbox ORDER BY seq LIMIT $max;";
            cmd.Parameters.AddWithValue("$max", max);
            using var reader = cmd.ExecuteReader();
            var items = new List<OutboxItem>();
            while (reader.Read())
            {
                items.Add(new OutboxItem(reader.GetString(0), reader.GetString(1), reader.GetString(2)));
            }
            return items;
        }
    }

    public void Remove(IEnumerable<string> ids)
    {
        lock (_lock)
        {
            using var tx = _db.BeginTransaction();
            using var cmd = _db.CreateCommand();
            cmd.Transaction = tx;
            cmd.CommandText = "DELETE FROM outbox WHERE id = $id;";
            var p = cmd.Parameters.Add("$id", SqliteType.Text);
            foreach (var id in ids)
            {
                p.Value = id;
                cmd.ExecuteNonQuery();
            }
            tx.Commit();
        }
    }

    public int Count()
    {
        lock (_lock)
        {
            using var cmd = _db.CreateCommand();
            cmd.CommandText = "SELECT COUNT(*) FROM outbox;";
            return Convert.ToInt32(cmd.ExecuteScalar());
        }
    }

    private void Execute(string sql)
    {
        using var cmd = _db.CreateCommand();
        cmd.CommandText = sql;
        cmd.ExecuteNonQuery();
    }

    public void Dispose() => _db.Dispose();
}
