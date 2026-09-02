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

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Kpi label="Tokens saved" value={fmt(s.tokens_saved)} accent="text-[#002FA7]" sub={`${s.token_reduction_pct}% smaller`} />
        <Kpi label="Tokens before → after" value={`${fmt(s.tokens_before)}`} sub={`→ ${fmt(s.tokens_after)} after`} />
        <Kpi label="Duplicates removed" value={fmt(s.duplicates_removed)} accent="text-[#FF3B30]" sub={`from ${fmt(s.fragments_in)} fragments`} />
        <Kpi label="Unique concepts" value={fmt(s.unique_concepts)} sub={`${fmt(s.near_dup_clusters)} near-dup merges`} />
      </div>

      {/* Chart + breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="card-brutal p-6 lg:col-span-2">
          <div className="overline mb-4">Token volume · before vs after</div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <XAxis dataKey="name" tick={{ fontFamily: "IBM Plex Mono", fontSize: 12, fill: "#0A0A0A" }} axisLine={{ stroke: "#0A0A0A" }} />
              <YAxis tick={{ fontFamily: "IBM Plex Mono", fontSize: 11, fill: "#9CA3AF" }} axisLine={{ stroke: "#0A0A0A" }} width={50} />
              <Tooltip cursor={{ fill: "#F3F4F6" }} contentStyle={{ border: "2px solid #0A0A0A", borderRadius: 2, fontFamily: "IBM Plex Mono" }} />
              <Bar dataKey="value" fill="#002FA7" stroke="#0A0A0A" strokeWidth={2} maxBarSize={140} isAnimationActive={false}>
                <Cell fill="#FF3B30" />
                <Cell fill="#002FA7" />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="card-brutal p-6">
          <div className="overline mb-4">Breakdown</div>
          <dl className="space-y-3 text-sm">
            {[
              ["Input fragments", fmt(s.fragments_in)],
              ["After exact dedup", fmt(s.after_exact_dedup)],
              ["After near-dup", fmt(s.unique_concepts)],
              ["Raw characters", fmt(s.raw_chars)],
              ["Threshold", s.threshold],
              ["Processing time", `${s.elapsed_ms} ms`],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between border-b border-dashed border-[#E5E7EB] pb-2">
                <dt className="text-[#4B5563]">{k}</dt>
                <dd className="font-bold tabular-nums">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>

      {/* Fragments */}
      <div>
        <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
          <h2 className="font-head font-bold text-xl tracking-tight">Deduplicated dataset</h2>
          <div className="relative">
            <MagnifyingGlass size={16} weight="bold" className="absolute left-3 top-1/2 -translate-y-1/2 text-[#9CA3AF]" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search fragments…"
              className="input-brutal pl-9 w-72"
              data-testid="fragment-search"
            />
          </div>
        </div>

        <div className="card-brutal overflow-hidden" data-testid="fragments-table">
          <table className="w-full text-sm">
            <thead className="bg-[#0A0A0A] text-white">
              <tr className="text-left uppercase text-xs tracking-wider">
                <th className="px-4 py-3 w-16 text-right">×</th>
                <th className="px-4 py-3">Canonical fragment</th>
                <th className="px-4 py-3 w-20 text-right">Tokens</th>
                <th className="px-4 py-3 w-24 text-right">Variants</th>
              </tr>
            </thead>
            <tbody>
              {frags.items.map((f, i) => (
                <tr key={i} className="border-t-2 border-[#0A0A0A] align-top" data-testid={`fragment-row-${i}`}>
                  <td className="px-4 py-3 text-right font-bold tabular-nums text-[#002FA7]">{f.count}</td>
                  <td className="px-4 py-3">
                    <div className="leading-relaxed">{f.text}</div>
                    {f.variant_count > 0 && (
                      <details className="mt-2">
                        <summary className="cursor-pointer text-xs uppercase tracking-wider text-[#9CA3AF] hover:text-[#002FA7]">
                          {f.variant_count} preserved variant{f.variant_count > 1 ? "s" : ""}
                        </summary>
                        <ul className="mt-2 space-y-1 border-l-2 border-[#E5E7EB] pl-3">
                          {f.variants.map((v, vi) => (
                            <li key={vi} className="text-xs text-[#4B5563]">{v}</li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">{f.tokens}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-[#9CA3AF]">{f.variant_count}</td>
                </tr>
              ))}
              {frags.items.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-10 text-center text-[#9CA3AF]">
                    No fragments match.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between mt-4">
          <div className="text-xs text-[#9CA3AF] uppercase tracking-wider">
            {fmt(frags.total)} unique fragments
          </div>
          <div className="flex items-center gap-3">
            <button
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
              className="btn-ghost py-1.5 px-2 disabled:opacity-40"
              data-testid="prev-page"
            >
              <CaretLeft size={16} weight="bold" />
            </button>
            <span className="text-sm font-bold tabular-nums">
              {page} / {totalPages}
            </span>
            <button
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
              className="btn-ghost py-1.5 px-2 disabled:opacity-40"
              data-testid="next-page"
            >
              <CaretRight size={16} weight="bold" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
