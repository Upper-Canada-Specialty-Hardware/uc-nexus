"""Read-only Microsoft Graph client for the legacy SharePoint inventory list.

The warehouse's inventory system of record before UC Nexus was a SharePoint list on the
UCH-Operations site. This module reads that list so the admin migration wizard can bring the
on-hand quantities across; nothing here ever writes to SharePoint.

Auth is app-only (client credentials), not delegated: the Entra app registration holds
application-type `Sites.ReadWrite.All` with tenant-wide admin consent, so there is no user to sign
in and no refresh token to keep. A token lasts about an hour and is cached module-level.

The site and list IDs are constants rather than settings because there is exactly one list this
migration reads, and it is retired once the migration has run.
"""

import asyncio
import logging
import time

import httpx

from app import config
from app.errors import AppError, ValidationError

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

SITE_ID = "ucshca.sharepoint.com,c6774f05-2afd-426a-a67d-995ff3519a41,e8c64346-73cd-49cd-84a6-282c8341b0d3"
LIST_ID = "9cf93050-6f8b-4f14-8933-dc6ef7e2f8cb"

# Only the columns the wizard reads. Selecting explicitly keeps the payload to a few hundred KB over
# 3.5k rows instead of pulling all 68 columns including barcode images and compliance lookups.
_FIELDS = (
    "Title",
    "HWSPartNumberEquivalent",
    "Part_x0020_Category_x0020_1",
    "Inventory_x0020_Type",
    "Locations",
    "Stock_x0020_Qty",
    "Non_x0020_Stock_x0020_Qty",
    "Project_x0020_Inventory_x0020_Qt",
    "Project_x0020_Number_x0020_Temp",
    "Project_x0020_Name_x0020_Temp",
    # Unit cost of the part. No PO line exists in Nexus for migrated stock (it was bought years ago in
    # the system being retired), so this is the only place the cost can come from. The internal name
    # really is "UnitCost" with no _x0020_ - confirmed against the list's columnDefinitions
    # (2026-08-18: currency column, display "Unit Cost", populated on ~91% of rows). The first guess
    # (Unit_x0020_Cost) selected nothing, which reads as no cost rather than an error - the review
    # step's all-costless warning is what catches a regression here.
    "UnitCost",
    # Descriptive columns. Only meaningful for non-schedule stock - a frame or a specialty is
    # described by these and by nothing else, since no hardware schedule describes it (#454).
    # There is NO Part Description column on the list (confirmed against columnDefinitions
    # 2026-08-18), so part_description always reads empty and the catalog's description falls back
    # to Part Category 1 - which is why no such select appears here.
    "Finish",
    "Rating",
    "Mounting",
    "Height_x0020_in_x0020_inches",
    "Width_x0020_in_x0020_inches",
)

_PAGE_SIZE = 2000
# 3.5k rows is two pages. The cap only exists so a Graph paging bug cannot spin forever.
_MAX_PAGES = 20

_REFRESH_BUFFER_SECONDS = 300

_token: str | None = None
_token_expires_at: float = 0.0
# asyncio, not threading: this is awaited from the event loop, and a threading.Lock held across an
# await would block every other request rather than just the second caller of this function.
_token_lock = asyncio.Lock()


class SharePointUnavailableError(AppError):
    """Graph could not be reached or refused the credentials."""

    def __init__(self, message: str):
        super().__init__(message, "SHAREPOINT_UNAVAILABLE")


def _require_credentials() -> None:
    missing = [
        name
        for name, value in (
            ("AZURE_TENANT_ID", config.AZURE_TENANT_ID),
            ("AZURE_CLIENT_ID", config.AZURE_CLIENT_ID),
            ("AZURE_CLIENT_SECRET", config.AZURE_CLIENT_SECRET),
        )
        if not value
    ]
    if missing:
        raise ValidationError(
            "SharePoint migration is not configured on this environment: " + ", ".join(missing) + " unset"
        )


def invalidate_token() -> None:
    """Drop the cached token so the next call re-acquires.

    Called when Graph rejects a token mid-read. Without it an expired client secret keeps a dead
    token cached for its full hour, so the wizard's Retry button re-sends the same rejected
    credential and the failure looks permanent when it is one refresh away from recoverable.
    """
    global _token, _token_expires_at
    _token = None
    _token_expires_at = 0.0


async def _get_token() -> str:
    """Acquire (or reuse) an app-only Graph token.

    Locked because two concurrent wizard fetches would otherwise both hit the token endpoint; the
    second would succeed but the request is pure waste and Entra rate-limits it.
    """
    global _token, _token_expires_at

    async with _token_lock:
        if _token and time.time() < _token_expires_at - _REFRESH_BUFFER_SECONDS:
            return _token

        _require_credentials()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"https://login.microsoftonline.com/{config.AZURE_TENANT_ID}/oauth2/v2.0/token",
                    data={
                        "client_id": config.AZURE_CLIENT_ID,
                        "client_secret": config.AZURE_CLIENT_SECRET,
                        "scope": "https://graph.microsoft.com/.default",
                        "grant_type": "client_credentials",
                    },
                    timeout=30,
                )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            # A 401 here is almost always an expired client secret, which is worth saying out loud
            # rather than leaving as a bare status code.
            logger.warning("Graph token request failed: %s %s", e.response.status_code, e.response.text[:400])
            raise SharePointUnavailableError(
                f"Microsoft Graph refused the app credentials ({e.response.status_code}). "
                "The client secret may have expired."
            ) from e
        except httpx.HTTPError as e:
            raise SharePointUnavailableError(f"Could not reach Microsoft Graph: {e}") from e

        data = resp.json()
        _token = data["access_token"]
        _token_expires_at = time.time() + data.get("expires_in", 3600)
        return _token


async def fetch_inventory_items() -> list[dict]:
    """Every row of the SharePoint inventory list, as flat `fields` dicts plus the SharePoint id.

    Returns the raw list verbatim - no filtering, no quantity interpretation. Deciding which rows
    carry migratable stock is the wizard's job, and doing it here would hide the source totals the
    first wizard step reports.

    Async because the migration is one-shot and non-idempotent, so a partial read is the expensive
    kind of wrong: this is the only chance to get the row set right. Blocking the event loop for the
    length of a multi-page Graph read would also freeze every other request to the backend, which is
    why every other external-system resolver here (the relay gp_* calls, registerPoInGp,
    syncGpJobs) is async too.
    """
    token = await _get_token()
    select = ",".join(_FIELDS)
    url = f"{GRAPH_BASE}/sites/{SITE_ID}/lists/{LIST_ID}/items?$expand=fields($select={select})&$top={_PAGE_SIZE}"

    items: list[dict] = []
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=120) as client:
        for _ in range(_MAX_PAGES):
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.warning("Graph list read failed: %s %s", e.response.status_code, e.response.text[:400])
                if e.response.status_code in (401, 403):
                    # The cached token is what was just refused; keeping it makes Retry re-send it.
                    invalidate_token()
                raise SharePointUnavailableError(
                    f"Microsoft Graph returned {e.response.status_code} reading the inventory list."
                ) from e
            except httpx.HTTPError as e:
                raise SharePointUnavailableError(f"Could not reach Microsoft Graph: {e}") from e

            payload = resp.json()
            for entry in payload.get("value", []):
                fields = entry.get("fields", {})
                items.append({"sp_item_id": str(entry.get("id", "")), **fields})

            next_link = payload.get("@odata.nextLink")
            if not next_link:
                break
            url = next_link
        else:
            # Refuse rather than return short. Graph honours $top=2000 on this list today (3.5k rows
            # arrive in two pages), but if it ever pages smaller, a truncated list that LOOKS
            # complete is the worst outcome available: the wizard would report a smaller source
            # total, migrate a subset, and leave the remainder unmigratable because a second run
            # duplicates everything the first one wrote.
            raise SharePointUnavailableError(
                f"The SharePoint list did not finish paging within {_MAX_PAGES} pages "
                f"({len(items)} rows read). Refusing to migrate a partial list."
            )

    logger.info("Fetched %d SharePoint inventory rows", len(items))
    return items
