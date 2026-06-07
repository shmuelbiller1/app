import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import {
  Stack,
  Key,
  ShieldCheck,
  SignOut,
  Lightning,
  ListBullets,
} from "@phosphor-icons/react";

const NavItem = ({ to, icon: Icon, label, active, testid }) => (
  <Link
    to={to}
    data-testid={testid}
    className={`flex items-center gap-3 px-4 py-3 border-2 rounded-sm font-bold uppercase tracking-wide text-sm transition-all duration-200 ${
      active
        ? "bg-[#0A0A0A] text-white border-[#0A0A0A]"
        : "bg-white text-[#0A0A0A] border-transparent hover:border-[#0A0A0A]"
    }`}
  >
    <Icon size={20} weight="bold" />
    {label}
  </Link>
);

export default function AppShell({ children }) {
  const { user, logout } = useAuth();
  const loc = useLocation();
  const navigate = useNavigate();
  const isActive = (p) => loc.pathname === p;

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div className="min-h-screen bg-[#F9FAFB] flex flex-col">
      {/* Top bar */}
      <header className="bg-white border-b-2 border-[#0A0A0A] sticky top-0 z-30">
        <div className="flex items-center justify-between px-6 h-16">
          <Link to="/app" className="flex items-center gap-2" data-testid="brand-logo">
            <Lightning size={26} weight="fill" className="text-[#002FA7]" />
            <span className="font-head font-black text-xl tracking-tighter">TOKENFORGE</span>
          </Link>
          <div className="flex items-center gap-4">
            <div className="text-right hidden sm:block">
              <div className="text-sm font-bold leading-none">{user?.name}</div>
              <div className="text-xs text-[#9CA3AF] uppercase tracking-wider">{user?.role}</div>
            </div>
            <button onClick={handleLogout} className="btn-ghost py-2 px-3" data-testid="logout-button">
              <SignOut size={18} weight="bold" />
            </button>
          </div>
        </div>
      </header>

      <div className="flex flex-1">
        {/* Sidebar */}
        <aside className="w-60 border-r-2 border-[#0A0A0A] bg-white p-4 hidden md:flex flex-col gap-2">
          <NavItem to="/app" icon={Stack} label="Optimizer" active={isActive("/app")} testid="nav-optimizer" />
          <NavItem to="/app/keys" icon={Key} label="API Keys" active={isActive("/app/keys")} testid="nav-keys" />
          {user?.role === "admin" && (
            <NavItem to="/admin" icon={ShieldCheck} label="Admin" active={isActive("/admin")} testid="nav-admin" />
          )}
          <div className="mt-auto pt-4 border-t-2 border-dashed border-[#E5E7EB]">
            <div className="overline mb-2 flex items-center gap-1">
              <ListBullets size={14} weight="bold" /> Docs
            </div>
            <p className="text-xs text-[#4B5563] leading-relaxed">
              POST <code className="text-[#002FA7]">/api/v1/optimize</code> with header{" "}
              <code className="text-[#002FA7]">X-API-Key</code>.
            </p>
          </div>
        </aside>

        <main className="flex-1 p-6 lg:p-10 max-w-[1400px] w-full mx-auto">{children}</main>
      </div>
    </div>
  );
}
