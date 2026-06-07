import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { formatApiErrorDetail } from "@/lib/api";
import { Lightning, ArrowRight } from "@phosphor-icons/react";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const u = await login(email, password);
      navigate(u.role === "admin" ? "/admin" : "/app");
    } catch (err) {
      setError(formatApiErrorDetail(err.response?.data?.detail) || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F9FAFB] flex items-center justify-center p-6">
      <div className="w-full max-w-md">
        <Link to="/" className="flex items-center gap-2 justify-center mb-8" data-testid="login-brand">
          <Lightning size={28} weight="fill" className="text-[#002FA7]" />
          <span className="font-head font-black text-2xl tracking-tighter">TOKENFORGE</span>
        </Link>
        <div className="card-brutal p-8">
          <div className="overline mb-1">Welcome back</div>
          <h1 className="font-head font-black text-3xl tracking-tight mb-6">Log in</h1>
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="overline block mb-1">Email</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input-brutal"
                data-testid="login-email"
                placeholder="you@company.com"
              />
            </div>
            <div>
              <label className="overline block mb-1">Password</label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input-brutal"
                data-testid="login-password"
                placeholder="••••••••"
              />
            </div>
            {error && (
              <div className="border-2 border-[#FF3B30] bg-[#FF3B30]/5 text-[#FF3B30] text-sm font-bold px-3 py-2 rounded-sm" data-testid="login-error">
                {error}
              </div>
            )}
            <button type="submit" disabled={loading} className="btn-brutal w-full" data-testid="login-submit">
              {loading ? "Authenticating…" : "Log in"} <ArrowRight size={18} weight="bold" />
            </button>
          </form>
          <p className="text-sm text-[#4B5563] mt-6 text-center">
            No account?{" "}
            <Link to="/register" className="text-[#002FA7] font-bold underline" data-testid="goto-register">
              Create one
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
