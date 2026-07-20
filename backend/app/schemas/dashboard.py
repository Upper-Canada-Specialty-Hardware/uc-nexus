"""Dashboard stat queries (home, shop assembly, admin)."""

import strawberry

from app.database import SessionLocal
from app.repositories import dashboard_repository, user_repository

from .types import AdminStats, HomeDashboardStats, ShopAssemblyStats


@strawberry.type
class DashboardQueries:
    @strawberry.field
    def home_dashboard_stats(self) -> HomeDashboardStats:
        with SessionLocal() as session:
            d = dashboard_repository.get_home_dashboard_stats(session)
            return HomeDashboardStats(
                open_po_count=d["open_po_count"],
                pending_pull_request_count=d["pending_pull_request_count"],
                items_pending_receiving=d["items_pending_receiving"],
                project_count=d["project_count"],
            )

    @strawberry.field
    def shop_assembly_stats(self) -> ShopAssemblyStats:
        with SessionLocal() as session:
            d = dashboard_repository.get_shop_assembly_stats(session)
            return ShopAssemblyStats(
                active_pull_request_count=d["active_pull_request_count"],
            )

    @strawberry.field
    def admin_stats(self) -> AdminStats:
        users = user_repository.list_users()
        with SessionLocal() as session:
            d = dashboard_repository.get_admin_stats(session, user_count=len(users))
            return AdminStats(
                vendor_count=d["vendor_count"],
                user_count=d["user_count"],
                hardware_item_count=d["hardware_item_count"],
                opening_count=d["opening_count"],
            )
