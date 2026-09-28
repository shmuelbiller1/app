import "@/App.css";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import QuantScanner from "@/pages/QuantScanner";

// The scanner is a static, zero-key dashboard.  Keeping the legacy auth shell
// mounted here made every page load request an unrelated TokenForge API.
export default function App() {
  return (
    <BrowserRouter>
      <Toaster position="top-right" />
      <Routes>
        <Route path="/" element={<QuantScanner />} />
        <Route path="/scanner" element={<Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
