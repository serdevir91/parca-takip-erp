import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth, type Module } from "./api/auth";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Projects from "./pages/Projects";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const Parts = lazy(() => import("./pages/Parts"));
const Fasteners = lazy(() => import("./pages/Fasteners"));
const BomVersions = lazy(() => import("./pages/BomVersions"));
const BomTree = lazy(() => import("./pages/BomTree"));
const Drawings = lazy(() => import("./pages/Drawings"));
const Control = lazy(() => import("./pages/Control"));
const Admin = lazy(() => import("./pages/Admin"));
const Planning = lazy(() => import("./pages/Planning"));
const Purchasing = lazy(() => import("./pages/Purchasing"));
const WorkOrders = lazy(() => import("./pages/WorkOrders"));
const Stock = lazy(() => import("./pages/Stock"));
const Home = lazy(() => import("./pages/Home"));
const Contacts = lazy(() => import("./pages/Contacts"));
const Sales = lazy(() => import("./pages/Sales"));
const Finance = lazy(() => import("./pages/Finance"));
const Hr = lazy(() => import("./pages/Hr"));
const MyCard = lazy(() => import("./pages/MyCard"));
const Chat = lazy(() => import("./pages/Chat"));

function RequireAuth({ children, module }: { children: ReactNode; module?: Module }) {
  const { user, ready, can } = useAuth();
  const loc = useLocation();
  if (!ready) return <div className="content muted">Yükleniyor…</div>;
  if (!user) return <Navigate to="/login" state={{ from: loc.pathname }} replace />;
  if (module && !can(module)) return <div className="content"><div className="card empty">Bu ekranı görme yetkiniz yok. Yöneticinizden yetki isteyin.</div></div>;
  return <>{children}</>;
}

const S = ({ children }: { children: ReactNode }) => (
  <Suspense fallback={<div className="content muted">Yükleniyor…</div>}>{children}</Suspense>
);

/** Lazy page behind a module permission. */
const M = ({ m, children }: { m: Module; children: ReactNode }) => <RequireAuth module={m}><S>{children}</S></RequireAuth>;

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth><Layout /></RequireAuth>}>
        <Route index element={<S><Home /></S>} />
        <Route path="projects" element={<M m="projects"><Projects /></M>} />
        <Route path="p/:pid">
          <Route index element={<M m="projects"><Dashboard /></M>} />
          <Route path="parts" element={<M m="parts"><Parts /></M>} />
          <Route path="fasteners" element={<M m="fasteners"><Fasteners /></M>} />
          <Route path="tree" element={<M m="projects"><BomTree /></M>} />
          <Route path="bom" element={<M m="projects"><BomVersions /></M>} />
          <Route path="drawings" element={<M m="drawings"><Drawings /></M>} />
          <Route path="control" element={<M m="control"><Control /></M>} />
          <Route path="planning" element={<M m="planning"><Planning /></M>} />
          <Route path="purchasing" element={<M m="purchasing"><Purchasing /></M>} />
          <Route path="work-orders" element={<M m="workorders"><WorkOrders /></M>} />
        </Route>
        <Route path="purchasing" element={<M m="purchasing"><Purchasing /></M>} />
        <Route path="work-orders" element={<M m="workorders"><WorkOrders /></M>} />
        <Route path="stock" element={<M m="stock"><Stock /></M>} />
        <Route path="hr" element={<M m="hr"><Hr /></M>} />
        <Route path="hr/me" element={<S><MyCard /></S>} />
        <Route path="contacts" element={<M m="contacts"><Contacts /></M>} />
        <Route path="sales" element={<M m="sales"><Sales /></M>} />
        <Route path="finance" element={<M m="finance"><Finance /></M>} />
        <Route path="chat" element={<M m="chat"><Chat /></M>} />
        <Route path="admin" element={<M m="admin"><Admin /></M>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
