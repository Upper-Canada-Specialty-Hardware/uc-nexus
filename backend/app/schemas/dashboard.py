"""Dashboard stat queries (home, shop assembly, admin)."""

import strawberry

from app import config
from app.auth import user_roster
from app.database import SessionLocal
from app.repositories import dashboard_repository

from .types import AdminStats, HomeDashboardStats, ShippingStats, ShopAssemblyStats


@strawberry.type
class DashboardQueries:
    @strawberry.field
    def home_dashboard_stats(self, info: strawberry.Info) -> HomeDashboardStats:
        with SessionLocal() as session:
            d = dashboard_repository.get_home_dashboard_stats(session)
            return HomeDashboardStats(
                open_po_count=d["open_po_count"],
                pending_pull_request_count=d["pending_pull_request_count"],
                items_pending_receiving=d["items_pending_receiving"],
                project_count=d["project_count"],
            )

    @strawberry.field
    def shop_assembly_stats(self, info: strawberry.Info) -> ShopAssemblyStats:
        with SessionLocal() as session:
            d = dashboard_repository.get_shop_assembly_stats(session)
            return ShopAssemblyStats(
                active_pull_request_count=d["active_pull_request_count"],
            )

    @strawberry.field
    def shipping_stats(self, info: strawberry.Info) -> ShippingStats:
        with SessionLocal() as session:
            d = dashboard_repository.get_shipping_stats(session)
            return ShippingStats(
                pending_request_count=d["pending_request_count"],
                staging_container_count=d["staging_container_count"],
                scheduled_shipment_count=d["scheduled_shipment_count"],
                in_transit_shipment_count=d["in_transit_shipment_count"],
            )

    @strawberry.field
    def admin_stats(self, info: strawberry.Info) -> AdminStats:
        """Admin-gated (#415): only the admin landing page reads it, and it enumerates Clerk users to
        count them.

        That enumeration is also what authorized the caller. `user_roster` is the request-scoped
        memo the gate resolved this field's Admin/Manager requirement from (ROSTER_BACKED in
        app/auth_policy.py) - the roster carries roles per user, so one Clerk call answers both
        questions. Calling `user_repository.list_users()` directly here would make it two, which is
        what it was before #423."""
        users = user_roster(info.context)
        with SessionLocal() as session:
            d = dashboard_repository.get_admin_stats(session, user_count=len(users))
            return AdminStats(
                user_count=d["user_count"],
                hardware_item_count=d["hardware_item_count"],
                opening_count=d["opening_count"],
                db_access_enabled=config.db_direct_access_enabled(),
            )
