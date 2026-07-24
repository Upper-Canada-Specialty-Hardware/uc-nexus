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

frontend and backend talk through a single /graphql endpoint.

core domain rule: hardware is procured per opening, loses that identity when it is received into
fungible inventory, and gets it back when a pull request tags it onto a specific door leaf of a
specific opening. read docs/HARDWARE_IDENTITY_LIFECYCLE.md before working on receiving, pull
requests, shop assembly or shipping out.
