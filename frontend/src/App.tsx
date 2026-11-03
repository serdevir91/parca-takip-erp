import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./api/auth";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Projects from "./pages/Projects";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const Parts = lazy(() => import("./pages/Parts"));
const Fasteners = lazy(() => import("./pages/Fasteners"));
const BomVersions = lazy(() => import("./pages/BomVersions"));
const Drawings = lazy(() => import("./pages/Drawings"));
const Control = lazy(() => import("./pages/Control"));
const Admin = lazy(() => import("./pages/Admin"));
const Planning = lazy(() => import("./pages/Planning"));
const Purchasing = lazy(() => import("./pages/Purchasing"));
const WorkOrders = lazy(() => import("./pages/WorkOrders"));
const Stock = lazy(() => import("./pages/Stock"));

function RequireAuth({ children, admin }: { children: ReactNode; admin?: boolean }) {
  const { user, ready, isAdmin } = useAuth();
  const loc = useLocation();
  if (!ready) return <div className="content muted">Yükleniyor…</div>;
  if (!user) return <Navigate to="/login" state={{ from: loc.pathname }} replace />;
  if (admin && !isAdmin) return <Navigate to="/" replace />;
  return <>{children}</>;
}

const S = ({ children }: { children: ReactNode }) => (
  <Suspense fallback={<div className="content muted">Yükleniyor…</div>}>{children}</Suspense>
);

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth><Layout /></RequireAuth>}>
        <Route index element={<Projects />} />
        <Route path="p/:pid">
          <Route index element={<S><Dashboard /></S>} />
          <Route path="parts" element={<S><Parts /></S>} />
          <Route path="fasteners" element={<S><Fasteners /></S>} />
          <Route path="bom" element={<S><BomVersions /></S>} />
          <Route path="drawings" element={<S><Drawings /></S>} />
          <Route path="control" element={<S><Control /></S>} />
          <Route path="planning" element={<S><Planning /></S>} />
          <Route path="purchasing" element={<S><Purchasing /></S>} />
          <Route path="work-orders" element={<S><WorkOrders /></S>} />
        </Route>
        <Route path="purchasing" element={<S><Purchasing /></S>} />
        <Route path="work-orders" element={<S><WorkOrders /></S>} />
        <Route path="stock" element={<S><Stock /></S>} />
        <Route path="admin" element={<RequireAuth admin><S><Admin /></S></RequireAuth>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
