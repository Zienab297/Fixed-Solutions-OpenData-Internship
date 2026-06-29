/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_GRAFANA_URL?: string;
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}