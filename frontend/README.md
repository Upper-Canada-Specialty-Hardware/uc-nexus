UC Nexus frontend

React 19 + TypeScript + Vite + Apollo Client 4 + MUI 7 + Tailwind CSS 4. talks to the backend
through the single /graphql endpoint (the Vite dev server proxies /graphql to :8000).

- npm ci - install
- npm run dev - vite dev server
- npm run lint - eslint
- npm run test:run - vitest single run
- npm run build - typescript check + production build

module structure, conventions, and the full dev guide live in ../CLAUDE.md.
