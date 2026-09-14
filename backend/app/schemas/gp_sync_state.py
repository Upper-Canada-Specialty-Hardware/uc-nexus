"""The GP SYNC STATE read behind NEXUS GP TRAFFIC's Nexus half (#679).

One field, and it answers whether or not a relay is connected: with nothing on the socket the page
still shows every company that has been mirrored and how far each one got, which is exactly the state
somebody is trying to understand when they open it.

Composed into the root Query via schemas/queries.py, never added to the root type directly (see
CLAUDE.md). The document itself is built by app/services/gp_sync_state.py - the same one the backend
pushes down the relay socket, so the admin page and the relay window cannot disagree.
"""

import asyncio

import strawberry

from app.services import gp_sync_state as gp_sync_state_service

from .converters import gp_sync_state_to_type
from .types import GpSyncState


@strawberry.type
class GpSyncStateQueries:
    @strawberry.field
    async def gp_sync_state(self, info: strawberry.Info) -> GpSyncState:
        """What the GP sync loops are doing right now and what they have already done.

        Async and off the loop: the snapshot reads the database, and this runs in the same process as
        the relay socket. Three aggregate queries, no PO rows - see the service."""
        return gp_sync_state_to_type(await asyncio.to_thread(gp_sync_state_service.snapshot))
