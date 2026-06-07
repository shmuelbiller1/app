import { Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import {
  Lightning,
  ArrowRight,
  Stack,
  Cpu,
  ShieldCheck,
  FileText,
  ChartBar,
  Key,
} from "@phosphor-icons/react";

const Stat = ({ value, label, accent }) => (
  <div className="card-brutal p-6">
    <div className={`font-head font-black text-4xl tracking-tighter ${accent || "text-[#0A0A0A]"}`}>
      {value}
    </div>
    <div className="overline mt-2">{label}</div>
  </div>
);

const Feature = ({ icon: Icon, title, body }) => (
  <div className="card-brutal p-6 hover:-translate-y-1 transition-transform duration-200">
    <div className="w-11 h-11 flex items-center justify-center bg-[#002FA7] border-2 border-[#0A0A0A] mb-4">
      <Icon size={22} weight="bold" className="text-white" />
    </div>
    <h3 className="font-head font-bold text-lg tracking-tight mb-2">{title}</h3>
    <p className="text-sm text-[#4B5563] leading-relaxed">{body}</p>
  </div>
);

export default function Landing() {
  const { user } = useAuth();
  const dest = user ? "/app" : "/register";

  return (
    <div className="min-h-screen bg-white">
      {/* Header */}
      <header className="border-b-2 border-[#0A0A0A]">
        <div className="max-w-[1300px] mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Lightning size={26} weight="fill" className="text-[#002FA7]" />
            <span className="font-head font-black text-xl tracking-tighter">TOKENFORGE</span>
          </div>
          <div className="flex items-center gap-3">
            <Link to="/login" className="btn-ghost py-2 px-4 text-xs" data-testid="header-login">
              Log in
            </Link>
            <Link to="/register" className="btn-brutal py-2 px-4 text-xs" data-testid="header-signup">
              Start free
            </Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="max-w-[1300px] mx-auto px-6 pt-16 pb-12 grid grid-cols-1 md:grid-cols-12 gap-8 items-start">
        <div className="md:col-span-7">
          <div className="overline mb-4">LLM Token Ingestion Optimizer</div>
          <h1 className="font-head font-black text-5xl sm:text-6xl tracking-tighter leading-[0.95]">
            Each piece of data,
            <br />
            kept <span className="text-[#002FA7]">exactly once.</span>
          </h1>
          <p className="mt-6 text-base text-[#4B5563] leading-relaxed max-w-xl">
            TokenForge ingests massive files (TXT · CSV · JSON · PDF · DOCX), collapses every exact
            and near-duplicate fragment with MinHash + LSH, and hands back a token-minimized dataset.
            Zero data loss. Counts and variants preserved. Built for the largest files physics allows.
          </p>
          <div className="mt-8 flex flex-wrap gap-4">
            <Link to={dest} className="btn-brutal" data-testid="hero-cta">
              Optimize your data <ArrowRight size={18} weight="bold" />
            </Link>
            <Link to="/login" className="btn-ghost" data-testid="hero-login">
              I have an account
            </Link>
          </div>
        </div>

        <div className="md:col-span-5 grid grid-cols-2 gap-4">
          <Stat value="↓ 60%+" label="Tokens removed" accent="text-[#002FA7]" />
          <Stat value="O(n)" label="LSH dedup" />
          <Stat value="50 MB" label="Max ingest" />
          <Stat value="0" label="Data lost" accent="text-[#FF3B30]" />
        </div>
      </section>

      {/* Pipeline strip */}
      <section className="border-y-2 border-[#0A0A0A] bg-[#0A0A0A] text-white">
        <div className="max-w-[1300px] mx-auto px-6 py-5 flex flex-wrap items-center gap-x-6 gap-y-2 font-mono text-sm">
          <span className="text-[#9CA3AF]">PIPELINE //</span>
          {["INGEST", "NORMALIZE", "EXACT DEDUP", "MINHASH·LSH", "CLUSTER", "RESOLVE", "EXPORT"].map(
            (s, i) => (
              <span key={s} className="flex items-center gap-2">
                <span className={i === 3 ? "text-[#002FA7]" : "text-white"}>{s}</span>
                {i < 6 && <span className="text-[#9CA3AF]">→</span>}
              </span>
            )
          )}
        </div>
      </section>

      {/* Features */}
      <section className="max-w-[1300px] mx-auto px-6 py-16">
        <h2 className="font-head font-black text-3xl sm:text-4xl tracking-tight mb-10">
          The smart way to cut LLM token cost.
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          <Feature
            icon={Stack}
            title="One pass, each fragment once"
            body="Every line, row or record is normalized and hashed a single time. Exact duplicates collapse instantly into one canonical entry."
          />
          <Feature
            icon={Cpu}
            title="MinHash + LSH near-dup"
            body="Locality-sensitive hashing finds semantically similar fragments in linear time — no slow pairwise O(n²) comparisons."
          />
          <Feature
            icon={ShieldCheck}
            title="Lose no data"
            body="Collapsed duplicates keep their occurrence count and distinct variants stay attached to the canonical record. Fully auditable."
          />
          <Feature
            icon={FileText}
            title="Any format"
            body="Plain text, CSV, JSON, PDF and DOCX are parsed into clean atomic fragments before optimization."
          />
          <Feature
            icon={ChartBar}
            title="Token accounting"
            body="See tokens before vs after with the cl100k tokenizer — exact savings, reduction %, and processing time."
          />
          <Feature
            icon={Key}
            title="API key access"
            body="Generate per-user keys and call /v1/optimize programmatically. Account login for the dashboard, keys for machines."
          />
        </div>
      </section>

      {/* CTA */}
      <section className="border-t-2 border-[#0A0A0A]">
        <div className="max-w-[1300px] mx-auto px-6 py-16 text-center">
          <h2 className="font-head font-black text-4xl sm:text-5xl tracking-tighter">
            Stop paying for duplicate tokens.
          </h2>
          <Link to={dest} className="btn-brutal mt-8 text-base px-8 py-3 inline-flex" data-testid="footer-cta">
            Get started — it&apos;s free <ArrowRight size={20} weight="bold" />
          </Link>
        </div>
      </section>

      <footer className="border-t-2 border-[#0A0A0A] py-6">
        <div className="max-w-[1300px] mx-auto px-6 text-xs text-[#9CA3AF] uppercase tracking-widest">
          TokenForge · Pure-algorithm token ingestion optimizer
        </div>
      </footer>
    </div>
  );
}
