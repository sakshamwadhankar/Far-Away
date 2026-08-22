/* ESLint 8 flat-less config for the Komvos desktop renderer + Electron main.
   AGENT.md rule 6: full type hints, no loose `any`. */
module.exports = {
  root: true,
  env: { browser: true, es2020: true, node: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  plugins: ['@typescript-eslint', 'react-refresh'],
  ignorePatterns: ['dist', 'dist-electron', 'node_modules', '.eslintrc.cjs'],
  rules: {
    // AGENT.md rule 6 — loose `any` is forbidden.
    '@typescript-eslint/no-explicit-any': 'error',
    // tsconfig already enforces noUnusedLocals/noUnusedParameters; keep ESLint
    // aligned with the `_`-prefix escape hatch TypeScript uses.
    '@typescript-eslint/no-unused-vars': [
      'error',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
    ],
    // `while (true) { ... break }` is idiomatic; keep the check for `if`/`?:`.
    // This matches ESLint 9's default (`checkLoops: 'allExceptWhileTrue'`).
    'no-constant-condition': ['error', { checkLoops: false }],
    // Fast-refresh hygiene. `useToast` and `isChatCompatible` are the two
    // long-standing companion exports that live next to their component by
    // design; they are named explicitly rather than silenced with inline
    // disable comments.
    'react-refresh/only-export-components': [
      'warn',
      { allowConstantExport: true, allowExportNames: ['useToast', 'isChatCompatible'] },
    ],
  },
  overrides: [
    {
      files: ['**/*.test.ts', '**/*.test.tsx', 'e2e/**/*.ts'],
      env: { node: true },
    },
  ],
};
