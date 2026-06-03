import { Routes, Route } from "react-router-dom";
import ProjectWorkspace from "./pages/ProjectWorkspace";
import ProjectView from "./pages/ProjectView";
import ErrorBoundary from "./components/ErrorBoundary";

export default function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route path="/" element={<ProjectWorkspace />} />
        <Route path="/project/:projectId" element={<ProjectView />} />
      </Routes>
    </ErrorBoundary>
  );
}
