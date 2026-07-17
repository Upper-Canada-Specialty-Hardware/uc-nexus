UC Nexus

door installation hardware management system. tracks hardware schedules imported from TITAN
(hardware schedule writing software) through the full lifecycle: import, purchase orders
(registered in Dynamics GP via the relay), warehouse receiving, shop assembly, and shipping out.

monorepo layout

- backend/ - Python 3.11, FastAPI + Strawberry GraphQL + SQLAlchemy 2.0 + Alembic, deploys to Railway
- frontend/ - React 19, TypeScript, Vite, Apollo Client 4, MUI 7, Tailwind CSS 4, deploys to Railway
- relay/ - on-prem exe bridging UC Nexus to Microsoft Dynamics GP via eConnect, see relay/README.md
- testing/ - simulated user testing knowledgebase
- docs/ - design docs

frontend and backend talk through a single /graphql endpoint. dev commands, conventions, and the
architecture guide live in CLAUDE.md.
