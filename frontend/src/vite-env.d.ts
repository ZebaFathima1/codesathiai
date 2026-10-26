/// <reference types="vite/client" />

/**
 * Build-time environment for the web client.
 *
 * `VITE_API_BASE_URL` points the app at a backend on another origin, such as
 * the Render deployment. Leave it unset when the API shares this origin.
 */
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
