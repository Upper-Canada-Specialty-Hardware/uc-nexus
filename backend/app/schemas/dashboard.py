"""Dashboard stat queries (home, shop assembly, admin)."""

import strawberry

from app import config
from app.auth import tenant_scope, user_roster
from app.database import SessionLocal
from app.repositories import dashboard_repository, user_repository

from .types import AdminStats, HomeDashboardStats, ShippingStats, ShopAssemblyStats


@strawberry.type
class DashboardQueries:
    @strawberry.field
    def home_dashboard_stats(self, info: strawberry.Info) -> HomeDashboardStats:
        with SessionLocal() as session:
            d = dashboard_repository.get_home_dashboard_stats(session, company=tenant_scope(info))
            return HomeDashboardStats(
                open_po_count=d["open_po_count"],
                pending_pull_request_count=d["pending_pull_request_count"],
                items_pending_receiving=d["items_pending_receiving"],
                project_count=d["project_count"],
            )

    @strawberry.field
    def shop_assembly_stats(self, info: strawberry.Info) -> ShopAssemblyStats:
        with SessionLocal() as session:
            d = dashboard_repository.get_shop_assembly_stats(session, company=tenant_scope(info))
            return ShopAssemblyStats(
                active_pull_request_count=d["active_pull_request_count"],
            )

    @strawberry.field
    def shipping_stats(self, info: strawberry.Info) -> ShippingStats:
        with SessionLocal() as session:
            d = dashboard_repository.get_shipping_stats(session, company=tenant_scope(info))
            return ShippingStats(
                pending_request_count=d["pending_request_count"],
                staging_container_count=d["staging_container_count"],
                scheduled_shipment_count=d["scheduled_shipment_count"],
                in_transit_shipment_count=d["in_transit_shipment_count"],
            )

    @strawberry.field
    def admin_stats(self, info: strawberry.Info) -> AdminStats:
        """The Tenant Owner landing's three counts, within the caller's own company.

        Role-gated (#415, #729): only that landing page reads it, and it enumerates Clerk users to
        count them. That enumeration is also what authorized the caller. `user_roster` is the
        request-scoped memo the gate resolved this field's requirement from (ROSTER_BACKED in
        app/auth_policy.py) - the roster carries roles per user, so one Clerk call answers both
        questions. Calling `user_repository.list_users()` directly here would make it two, which is
        what it was before #423.

        The roster is company-wide, so a scoped caller's user count is filtered here rather than in
        the repository: the accounts live in Clerk, not in Postgres, and their company is a
        publicMetadata key the roster already carries. The stored value is normalized before
        comparing, the same way `caller_company` normalizes it, so a company saved with different
        casing cannot land on the wrong side of the count."""
        company = tenant_scope(info)
        users = user_roster(info.context)
        if company is not None:
            users = [u for u in users if user_repository.normalize_company(u.get("company")) == company]
        with SessionLocal() as session:
            d = dashboard_repository.get_admin_stats(session, user_count=len(users), company=company)
            return AdminStats(
                user_count=d["user_count"],
                hardware_item_count=d["hardware_item_count"],
                opening_count=d["opening_count"],
                db_access_enabled=config.db_direct_access_enabled(),
            )
