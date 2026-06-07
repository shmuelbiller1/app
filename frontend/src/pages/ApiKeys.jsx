import { useEffect, useState } from "react";
import api, { API, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { Key, Plus, Copy, Trash, Check, Terminal } from "@phosphor-icons/react";

export default function ApiKeys() {
  const [keys, setKeys] = useState([]);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [newKey, setNewKey] = useState(null);
  const [copied, setCopied] = useState(false);

  const load = async () => {
    const { data } = await api.get("/keys");
    setKeys(data);
  };

  useEffect(() => {
    api.get("/keys").then((r) => setKeys(r.data));
  }, []);

  const create = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try {
      const { data } = await api.post("/keys", { name: name.trim() });
      setNewKey(data);
      setName("");
      await load();
      toast.success("API key created — copy it now, it won't be shown again");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || err.message);
    } finally {
      setCreating(false);
    }
  };

  const revoke = async (id) => {
    try {
      await api.delete(`/keys/${id}`);
      await load();
      toast.success("Key revoked");
    } catch (e) {
      toast.error("Revoke failed");
    }
  };

  const copy = async (txt) => {
    await navigator.clipboard.writeText(txt);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="space-y-8" data-testid="api-keys-page">
      <div>
        <div className="overline mb-1">Programmatic access</div>
        <h1 className="font-head font-black text-4xl tracking-tighter">API Keys</h1>
        <p className="text-sm text-[#4B5563] mt-2 max-w-2xl">
          Use a key in the <code className="text-[#002FA7]">X-API-Key</code> header to call the
          optimizer from your own code. Keys are shown only once at creation.
        </p>
      </div>

      {/* Create */}
      <form onSubmit={create} className="card-brutal p-6 flex gap-3 flex-wrap items-end">
        <div className="flex-1 min-w-[220px]">
          <label className="overline block mb-1">Key name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Production server"
            className="input-brutal"
            data-testid="key-name-input"
          />
        </div>
        <button type="submit" disabled={creating} className="btn-brutal" data-testid="create-key-button">
          <Plus size={18} weight="bold" /> Generate key
        </button>
      </form>

      {/* New key reveal */}
      {newKey && (
        <div className="card-brutal-blue p-6" data-testid="new-key-reveal">
          <div className="overline mb-2 text-[#002FA7]">Copy now — shown once</div>
          <div className="flex items-center gap-3 bg-[#0A0A0A] text-white p-3 rounded-sm font-mono text-sm overflow-x-auto">
            <span className="flex-1 break-all" data-testid="new-key-value">{newKey.api_key}</span>
            <button onClick={() => copy(newKey.api_key)} className="text-white hover:text-[#002FA7] shrink-0" data-testid="copy-new-key">
              {copied ? <Check size={20} weight="bold" /> : <Copy size={20} weight="bold" />}
            </button>
          </div>
        </div>
      )}

      {/* Keys list */}
      <div>
        <h2 className="font-head font-bold text-xl tracking-tight mb-4">Your keys</h2>
        {keys.length === 0 ? (
          <div className="card-brutal p-10 text-center text-[#9CA3AF]" data-testid="no-keys">No keys yet.</div>
        ) : (
          <div className="card-brutal overflow-hidden" data-testid="keys-list">
            <table className="w-full text-sm">
              <thead className="bg-[#0A0A0A] text-white">
                <tr className="text-left uppercase text-xs tracking-wider">
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Prefix</th>
                  <th className="px-4 py-3 text-right">Uses</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => (
                  <tr key={k.id} className="border-t-2 border-[#0A0A0A]" data-testid={`key-row-${k.id}`}>
                    <td className="px-4 py-3 font-bold flex items-center gap-2">
                      <Key size={16} weight="bold" className="text-[#002FA7]" /> {k.name}
                    </td>
                    <td className="px-4 py-3 font-mono text-[#4B5563]">{k.prefix}…</td>
                    <td className="px-4 py-3 text-right tabular-nums">{k.usage_count}</td>
                    <td className="px-4 py-3">
                      {k.revoked ? (
                        <span className="text-xs font-bold uppercase text-[#FF3B30]">Revoked</span>
                      ) : (
                        <span className="text-xs font-bold uppercase text-[#34C759]">Active</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {!k.revoked && (
                        <button onClick={() => revoke(k.id)} className="text-[#9CA3AF] hover:text-[#FF3B30]" data-testid={`revoke-key-${k.id}`}>
                          <Trash size={18} weight="bold" />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Docs */}
      <div className="card-brutal p-6">
        <div className="overline mb-3 flex items-center gap-2">
          <Terminal size={16} weight="bold" /> Quick start
        </div>
        <pre className="bg-[#0A0A0A] text-white p-4 rounded-sm text-xs overflow-x-auto leading-relaxed">
{`curl -X POST "${API}/v1/optimize" \\
  -H "X-API-Key: tio_your_key_here" \\
  -H "Content-Type: application/json" \\
  -d '{"text": "your raw text...", "threshold": 0.82}'`}
        </pre>
      </div>
    </div>
  );
}
