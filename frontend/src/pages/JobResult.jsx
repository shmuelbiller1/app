import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api, { API } from "@/lib/api";
import { toast } from "sonner";
import { BarChart, Bar, XAxis, YAxis, Cell, ResponsiveContainer, Tooltip } from "recharts";
import {
  ArrowLeft,
  DownloadSimple,
  MagnifyingGlass,
  CaretLeft,
  CaretRight,
  Copy,
} from "@phosphor-icons/react";

const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString());

const Kpi = ({ label, value, accent, sub }) => (
  <div className="card-brutal p-5">
    <div className="overline">{label}</div>
    <div className={`font-head font-black text-3xl tracking-tighter mt-1 ${accent || ""}`}>{value}</div>
    {sub && <div className="text-xs text-[#9CA3AF] mt-1">{sub}</div>}
  </div>
);

export default function JobResult() {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState(null);
  const [frags, setFrags] = useState({ items: [], total: 0, page: 1, page_size: 25 });
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    api.get(`/jobs/${jobId}`).then((r) => setJob(r.data)).catch(() => navigate("/app"));
  }, [jobId, navigate]);

  useEffect(() => {
    const t = setTimeout(() => {
      setDebounced(search);
      setPage(1);
    }, 400);
    return () => clearTimeout(t);
  }, [search]);

  const loadFrags = useCallback(() => {
    api
      .get(`/jobs/${jobId}/fragments`, {
        params: { page, page_size: 25, search: debounced },
      })
      .then((r) => setFrags(r.data));
  }, [jobId, page, debounced]);

  useEffect(() => {
    loadFrags();
  }, [loadFrags]);

  const exportJson = () => {
    window.open(`${API}/jobs/${jobId}/export`, "_blank");
  };

  const copyText = async () => {
    try {
      const { data } = await api.get(`/jobs/${jobId}/export`);
      await navigator.clipboard.writeText(data.optimized_text || "");
      toast.success("Optimized text copied to clipboard");
    } catch (e) {
      toast.error("Copy failed");
    }
  };

  if (!job) return <div className="text-[#9CA3AF]">Loading…</div>;
  const s = job.stats || {};
  const totalPages = Math.max(1, Math.ceil(frags.total / 25));

  const chartData = [
    { name: "Before", value: s.tokens_before || 0 },
    { name: "After", value: s.tokens_after || 0 },
  ];

  return (
    <div className="space-y-8" data-testid="job-result">
      <button onClick={() => navigate("/app")} className="btn-ghost py-2 px-3 text-xs" data-testid="back-button">
        <ArrowLeft size={16} weight="bold" /> Back
      </button>

      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="overline mb-1">Result · {job.filename}</div>
          <h1 className="font-head font-black text-4xl tracking-tighter">Token report</h1>
        </div>
        <div className="flex gap-3">
          <button onClick={copyText} className="btn-ghost" data-testid="copy-text-button">
            <Copy size={18} weight="bold" /> Copy text
          </button>
          <button onClick={exportJson} className="btn-brutal" data-testid="export-button">
            <DownloadSimple size={18} weight="bold" /> Export JSON
          </button>
        </div>
      </div>

      <div className="grid md:grid-cols-4 gap-4">
        <Kpi label="Tokens before" value={fmt(s.tokens_before)} />
        <Kpi label="Tokens after" value={fmt(s.tokens_after)} accent="text-[#F8F83B]" />
        <Kpi label="Savings" value={s.tokens_before ? `${(((s.tokens_before - s.tokens_after) / s.tokens_before) * 100).toFixed(1)}%` : "—"} />
        <Kpi label="Fragments" value={fmt(s.fragment_count)} />
      </div>

      <div className="card-brutal p-5 h-72">
        <div className="overline mb-2">Token comparison</div>
        <ResponsiveContainer width="100%" height="85%">
          <BarChart data={chartData}>
            <XAxis dataKey="name" />
            <YAxis />
            <Tooltip />
            <Bar dataKey="value" fill="currentColor" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="card-brutal p-5 space-y-4">
        <div className="flex items-center gap-2">
          <MagnifyingGlass size={18} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search fragments…"
            className="input-brutal flex-1"
          />
        </div>
        <div className="space-y-2">
          {(frags.items || []).map((frag) => (
            <div key={frag.id || frag.fragment_id || JSON.stringify(frag)} className="border border-white/10 p-3 text-sm">
              <pre className="whitespace-pre-wrap break-words font-mono">{frag.text || frag.content || JSON.stringify(frag)}</pre>
            </div>
          ))}
        </div>
        <div className="flex items-center justify-between text-xs text-[#9CA3AF]">
          <span>Page {frags.page || page} of {totalPages}</span>
          <div className="flex gap-2">
            <button className="btn-ghost" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}><CaretLeft size={14} /> Prev</button>
            <button className="btn-ghost" disabled={page >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))}>Next <CaretRight size={14} /></button>
          </div>
        </div>
      </div>
    </div>
  );
}
