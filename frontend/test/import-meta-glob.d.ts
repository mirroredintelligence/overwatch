// `import.meta.glob` is Vite's: vitest transforms it at test time. Its type is declared here, for the
// one use that scans the BFF route files (test/guards/bff-routes.test.ts), so the project does not
// depend on Vite's own type package.
interface ImportMeta {
  glob<T = unknown>(pattern: string | string[]): Record<string, () => Promise<T>>;
}
