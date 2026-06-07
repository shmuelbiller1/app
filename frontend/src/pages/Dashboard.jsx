import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import {
  UploadSimple,
  FileText,
  Spinner,
  CheckCircle,
  XCircle,
  Trash,
  ArrowRight,
} from "@phosphor-icons/react";

const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString());

function StatusBadge({ status }) {
  const map = {
    completed: { c: "text-[#34C759] border-[#34C759]", I: CheckCircle, t: "Done" },
    processing: { c: "text-[#002FA7] border-[#002FA7]", I: Spinner, t: "Processing" },
    failed: { c: "text-[#FF3B30] border-[#FF3B30]", I: XCircle, t: "Failed" },
  };
  const m = map[status] || map.processing;
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-bold uppercase border-2 px-2 py-0.5 rounded-sm ${m.c}`}>
      <m.I size={14} weight="bold" className={status === "processing" ? "animate-spin" : ""} /> {m.t}
    </span>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState([]);
  const [threshold, setThreshold] = useState(0.82);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef(null);
  const pollRef = useRef(null);

  const loadJobs = useCallback(async () => {
    try {
      const { data } = await api.get("/jobs");
      setJobs(data);
      return data;
    } catch (e) {
      return [];
    }
  }, []);

  useEffect(() => {
    api
      .get("/jobs")
      .then((r) => setJobs(r.data))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const anyProcessing = jobs.some((j) => j.status === "processing");
    if (anyProcessing && !pollRef.current) {
      pollRef.current = setInterval(loadJobs, 1500);
    } else if (!anyProcessing && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {};
  }, [jobs, loadJobs]);

  useEffect(() => () => pollRef.current && clearInterval(pollRef.current), []);

  const upload = async (file) => {
    if (!file) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      await api.post(`/jobs?threshold=${threshold}`, form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(`Optimizing ${file.name}…`);
      await loadJobs();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files?.[0]) upload(e.dataTransfer.files[0]);
  };

  const remove = async (id, e) => {
    e.stopPropagation();
    try {
      await api.delete(`/jobs/${id}`);
      setJobs((j) => j.filter((x) => x.id !== id));
      toast.success("Job deleted");
    } catch (err) {
      toast.error("Delete failed");
    }
  };

  return (
    <div className="space-y-8" data-testid="dashboard">
      <div>
        <div className="overline mb-1">Optimizer</div>
        <h1 className="font-head font-black text-4xl tracking-tighter">Ingest & dedup</h1>
        <p className="text-sm text-[#4B5563] mt-2 max-w-2xl">
          Drop a TXT, CSV, JSON, PDF or DOCX file (up to 50 MB). Each piece of data is kept exactly
          once — duplicates and near-duplicates collapse with full audit trail.
        </p>
      </div>

      {/* Upload zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => fileRef.current?.click()}
        data-testid="upload-zone"
        className={`card-brutal p-10 cursor-pointer transition-all duration-200 text-center ${
          dragOver ? "shadow-[6px_6px_0px_#002FA7] -translate-y-0.5" : ""
        }`}
      >
        <input
          ref={fileRef}
          type="file"
          accept=".txt,.csv,.tsv,.json,.pdf,.docx"
          className="hidden"
          onChange={(e) => upload(e.target.files?.[0])}
          data-testid="file-input"
        />
        <div className="flex flex-col items-center gap-3">
          <div className="w-14 h-14 flex items-center justify-center bg-[#002FA7] border-2 border-[#0A0A0A]">
            {uploading ? (
              <Spinner size={26} weight="bold" className="text-white animate-spin" />
            ) : (
              <UploadSimple size={26} weight="bold" className="text-white" />
            )}
          </div>
          <div className="font-head font-bold text-lg">
            {uploading ? "Uploading…" : "Drop file or click to upload"}
          </div>
          <div className="overline">TXT · CSV · JSON · PDF · DOCX · max 50MB</div>
        </div>
      </div>

      {/* Threshold control */}
      <div className="card-brutal p-6">
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div>
            <div className="overline mb-1">Near-duplicate similarity threshold</div>
            <p className="text-sm text-[#4B5563]">
              Higher = stricter (only very similar fragments merge). Lower = more aggressive dedup.
            </p>
          </div>
          <div className="flex items-center gap-4">
            <input
              type="range"
              min={0.5}
              max={1}
              step={0.01}
              value={threshold}
              onChange={(e) => setThreshold(parseFloat(e.target.value))}
              className="w-48 accent-[#002FA7]"
              data-testid="threshold-slider"
            />
            <span className="font-head font-black text-2xl tabular-nums w-16 text-right" data-testid="threshold-value">
              {threshold.toFixed(2)}
            </span>
          </div>
        </div>
      </div>

      {/* Jobs table */}
      <div>
        <h2 className="font-head font-bold text-xl tracking-tight mb-4">Recent jobs</h2>
        {jobs.length === 0 ? (
          <div className="card-brutal p-10 text-center text-[#9CA3AF]" data-testid="no-jobs">
            No jobs yet. Upload a file to begin.
          </div>
        ) : (
          <div className="card-brutal overflow-hidden" data-testid="jobs-list">
            <table className="w-full text-sm">
              <thead className="bg-[#0A0A0A] text-white">
                <tr className="text-left uppercase text-xs tracking-wider">
                  <th className="px-4 py-3">File</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Tokens saved</th>
                  <th className="px-4 py-3 text-right">Reduction</th>
                  <th className="px-4 py-3 text-right">Time</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr
                    key={j.id}
                    onClick={() => j.status === "completed" && navigate(`/app/jobs/${j.id}`)}
                    className={`border-t-2 border-[#0A0A0A] ${
                      j.status === "completed" ? "cursor-pointer hover:bg-[#F3F4F6]" : ""
                    }`}
                    data-testid={`job-row-${j.id}`}
                  >
                    <td className="px-4 py-3 font-bold flex items-center gap-2">
                      <FileText size={18} weight="bold" className="text-[#002FA7]" />
                      <span className="truncate max-w-[200px]">{j.filename}</span>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={j.status} />
                      {j.status === "failed" && (
                        <div className="text-xs text-[#FF3B30] mt-1">{j.error}</div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums font-bold text-[#002FA7]">
                      {fmt(j.stats?.tokens_saved)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums font-bold">
                      {j.stats ? `${j.stats.token_reduction_pct}%` : "—"}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-[#4B5563]">
                      {j.stats ? `${j.stats.elapsed_ms}ms` : "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        {j.status === "completed" && (
                          <ArrowRight size={18} weight="bold" className="text-[#002FA7]" />
                        )}
                        <button
                          onClick={(e) => remove(j.id, e)}
                          className="text-[#9CA3AF] hover:text-[#FF3B30]"
                          data-testid={`delete-job-${j.id}`}
                        >
                          <Trash size={18} weight="bold" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
