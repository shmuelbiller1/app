import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { formatApiErrorDetail } from "@/lib/api";
import { Lightning, ArrowRight } from "@phosphor-icons/react";

export default function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await register(name, email, password);
      navigate("/app");
    } catch (err) {
      setError(formatApiErrorDetail(err.response?.data?.detail) || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F9FAFB] flex items-center justify-center p-6">
      <div className="w-full max-w-md">
        <Link to="/" className="flex items-center gap-2 justify-center mb-8" data-testid="register-brand">
          <Lightning size={28} weight="fill" className="text-[#002FA7]" />
          <span className="font-head font-black text-2xl tracking-tighter">TOKENFORGE</span>
        </Link>
        <div className="card-brutal p-8">
          <div className="overline mb-1">Get started free</div>
          <h1 className="font-head font-black text-3xl tracking-tight mb-6">Create account</h1>
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="overline block mb-1">Name</label>
              <input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="input-brutal"
                data-testid="register-name"
                placeholder="Ada Lovelace"
              />
            </div>
            <div>
              <label className="overline block mb-1">Email</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input-brutal"
                data-testid="register-email"
                placeholder="you@company.com"
              />
            </div>
            <div>
              <label className="overline block mb-1">Password</label>
              <input
                type="password"
                required
                minLength={6}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input-brutal"
                data-testid="register-password"
                placeholder="min 6 characters"
              />
            </div>
            {error && (
              <div className="border-2 border-[#FF3B30] bg-[#FF3B30]/5 text-[#FF3B30] text-sm font-bold px-3 py-2 rounded-sm" data-testid="register-error">
                {error}
              </div>
            )}
            <button type="submit" disabled={loading} className="btn-brutal w-full" data-testid="register-submit">
              {loading ? "Creating…" : "Create account"} <ArrowRight size={18} weight="bold" />
            </button>
          </form>
          <p className="text-sm text-[#4B5563] mt-6 text-center">
            Already have an account?{" "}
            <Link to="/login" className="text-[#002FA7] font-bold underline" data-testid="goto-login">
              Log in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
