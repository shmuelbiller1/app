import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import AppShell from "@/components/AppShell";
import Landing from "@/pages/Landing";
import Login from "@/pages/Login";
import Register from "@/pages/Register";
import Dashboard from "@/pages/Dashboard";
import JobResult from "@/pages/JobResult";
import ApiKeys from "@/pages/ApiKeys";
import Admin from "@/pages/Admin";

function Loading() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-white">
      <div className="font-mono text-sm uppercase tracking-[0.3em] text-[#9CA3AF] animate-pulse">
        Loading…
      </div>
    </div>
  );
}

function Protected({ children, adminOnly }) {
  const { user } = useAuth();
  if (user === null) return <Loading />;
  if (!user) return <Navigate to="/login" replace />;
  if (adminOnly && user.role !== "admin") return <Navigate to="/app" replace />;
  return <AppShell>{children}</AppShell>;
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Toaster
          position="top-right"
          toastOptions={{
            style: {
              border: "2px solid #0A0A0A",
              borderRadius: 2,
              fontFamily: "IBM Plex Mono",
              boxShadow: "4px 4px 0px #0A0A0A",
            },
          }}
        />
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/app" element={<Protected><Dashboard /></Protected>} />
          <Route path="/app/keys" element={<Protected><ApiKeys /></Protected>} />
          <Route path="/app/jobs/:jobId" element={<Protected><JobResult /></Protected>} />
          <Route path="/admin" element={<Protected adminOnly><Admin /></Protected>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
