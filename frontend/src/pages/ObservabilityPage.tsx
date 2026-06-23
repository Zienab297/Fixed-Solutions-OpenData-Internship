import { ExternalLink, RefreshCw } from "lucide-react";
import { useState } from "react";

/**
 * Embeds the Grafana dashboard directly in the app instead of opening
 * it in a new tab. Requires GF_SECURITY_ALLOW_EMBEDDING=true and
 * anonymous Viewer access on the Grafana side (see
 * infrastructure/docker/docker-compose.dev.yml) -- that grants
 * read-only dashboard viewing inside Grafana itself, separate from
 * this app's own RBAC, which is what actually gates who can land on
 * this route (see AppShell's hasRole("admin") check).
 */
const GRAFANA_BASE_URL = import.meta.env.VITE_GRAFANA_URL ?? "http://localhost:3001";
const DASHBOARD_UID = "rag-platform-overview";

export default function ObservabilityPage() {
  // Bump this to force the iframe to refetch rather than serving a
  // cached panel render.
  const [reloadKey, setReloadKey] = useState(0);

  const dashboardUrl = `${GRAFANA_BASE_URL}/d/${DASHBOARD_UID}/rag-platform-overview?orgId=1&kiosk=tv&theme=light&refresh=10s`;

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">Observability</h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Live metrics from Prometheus, rendered by Grafana.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="button-secondary"
            onClick={() => setReloadKey((k) => k + 1)}
          >
            <RefreshCw size={16} />
            Reload
          </button>
          <a
            href={`${GRAFANA_BASE_URL}/d/${DASHBOARD_UID}`}
            target="_blank"
            rel="noreferrer"
            className="button-secondary"
          >
            <ExternalLink size={16} />
            Open in Grafana
          </a>
        </div>
      </div>

      <div className="flex-1 overflow-hidden rounded-lg border border-zinc-200 dark:border-zinc-800">
        <iframe
          key={reloadKey}
          src={dashboardUrl}
          title="RAG Platform Observability"
          className="h-full w-full border-0"
          // Grafana's own login/anonymous-viewer flow runs inside this
          // frame; no need for allow-same-origin beyond what Grafana
          // itself requires to set its session.
          sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
        />
      </div>
    </div>
  );
}