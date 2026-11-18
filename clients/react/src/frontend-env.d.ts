declare module '*.css';

interface ImportMetaEnv {
  readonly VITE_AUTH_ACCOUNT_LIFECYCLE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
