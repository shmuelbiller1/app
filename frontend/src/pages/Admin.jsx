import { useEffect, useState } from "react";
import api from "@/lib/api";
import { toast } from "sonner";
import { Users, Lightning, Key, ChartLineUp, Trash, Power } from "@phosphor-icons/react";

const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString());

const Kpi = ({ icon: Icon, label, value, accent }) => (
  <div className="card-brutal p-5">
    <div className="flex items-center gap-2 overline mb-2">
      <Icon size={16} weight="bold" /> {label}
    </div>
    <div className={`font-head font-black text-3xl tracking-tighter ${accent || ""}`}>{value}</div>
  </div>
);

export default function Admin() {
  const [stats, setStats] = useState(null);
  const [users, setUsers] = useState([]);

  const load = async () => {
    const [s, u] = await Promise.all([api.get("/admin/stats"), api.get("/admin/users")]);
    setStats(s.data);
    setUsers(u.data);
  };

  useEffect(() => {
    Promise.all([api.get("/admin/stats"), api.get("/admin/users")]).then(([s, u]) => {
      setStats(s.data);
      setUsers(u.data);
    });
  }, []);

  const toggle = async (u) => {
    try {
      await api.patch(`/admin/users/${u.id}`, { active: !u.active });
      await load();
      toast.success(`${u.email} ${!u.active ? "activated" : "deactivated"}`);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Update failed");
    }
  };

  const del = async (u) => {
    if (!window.confirm(`Delete ${u.email} and all their data?`)) return;
    try {
      await api.delete(`/admin/users/${u.id}`);
      await load();
      toast.success("User deleted");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Delete failed");
    }
  };

  return (
    <div className="space-y-8" data-testid="admin-page">
      <div>
        <div className="overline mb-1">Owner console</div>
        <h1 className="font-head font-black text-4xl tracking-tighter">Admin</h1>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Kpi icon={Users} label="Users" value={fmt(stats?.total_users)} />
        <Kpi icon={Power} label="Active" value={fmt(stats?.active_users)} accent="text-[#34C759]" />
        <Kpi icon={Lightning} label="Jobs run" value={fmt(stats?.total_jobs)} />
        <Kpi icon={Key} label="Active keys" value={fmt(stats?.active_keys)} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Kpi icon={ChartLineUp} label="Total tokens saved" value={fmt(stats?.total_tokens_saved)} accent="text-[#002FA7]" />
        <Kpi icon={ChartLineUp} label="Total tokens processed" value={fmt(stats?.total_tokens_processed)} />
      </div>

      <div>
        <h2 className="font-head font-bold text-xl tracking-tight mb-4">All users</h2>
        <div className="card-brutal overflow-hidden" data-testid="users-table">
          <table className="w-full text-sm">
            <thead className="bg-[#0A0A0A] text-white">
              <tr className="text-left uppercase text-xs tracking-wider">
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3 text-right">Jobs</th>
                <th className="px-4 py-3 text-right">Keys</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-t-2 border-[#0A0A0A]" data-testid={`user-row-${u.id}`}>
                  <td className="px-4 py-3 font-bold">{u.name}</td>
                  <td className="px-4 py-3 text-[#4B5563]">{u.email}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-bold uppercase ${u.role === "admin" ? "text-[#002FA7]" : "text-[#4B5563]"}`}>
                      {u.role}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">{u.job_count}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{u.key_count}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-bold uppercase ${u.active ? "text-[#34C759]" : "text-[#FF3B30]"}`}>
                      {u.active ? "Active" : "Disabled"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {u.role !== "admin" && (
                      <div className="flex items-center justify-end gap-3">
                        <button onClick={() => toggle(u)} className="text-[#9CA3AF] hover:text-[#002FA7]" title="Toggle active" data-testid={`toggle-user-${u.id}`}>
                          <Power size={18} weight="bold" />
                        </button>
                        <button onClick={() => del(u)} className="text-[#9CA3AF] hover:text-[#FF3B30]" title="Delete" data-testid={`delete-user-${u.id}`}>
                          <Trash size={18} weight="bold" />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
