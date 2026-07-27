"""One live assembled leaf, structurally; and pull_status really is binary (#345, #350)

Revision ID: 065
Revises: 064
Create Date: 2026-07-26

Two invariants that the code already believed and the database did not enforce.

**One live `OpeningItem` per (project, opening, leaf).** `complete_opening` refuses to assemble a
leaf that already has a live assembled unit (#339's duplicate-completion guard), because minting a
second one for a single physical door leaf double-counts inventory and lets the same leaf ship
twice. That guard is a read followed by a write, so two assemblers finishing the two
ShopAssemblyOpenings that name the same leaf - a reopened-and-re-imported request, or a leaf sent to
the shop twice - can both pass it. A partial unique index makes it an invariant instead of a race:
`(project_id, opening_id, coalesce(leaf, 0)) WHERE state <> 'SHIPPED_OUT'`.

`coalesce(leaf, 0)` rather than a plain `leaf` column because NULLs do not collide in a unique index
and a legacy whole-opening unit (leaf IS NULL) is exactly as singular as leaf 1 or leaf 2. The
`WHERE` clause is the same shape as the guard it hardens: a **shipped** leaf has left the building
and a correction is allowed to assemble another one, which is precisely what
`find_already_assembled_openings` and `find_assembled_leaf` already encode.

Upgrade refuses to run on a database that already violates it, naming the offenders, rather than
picking a row to keep. A dev database should be clean; if one is not, silently deduplicating real
assembled leaves is a worse outcome than a loud stop.

**`shop_assembly_openings.pull_status` is NOT_PULLED or PULLED, never PARTIAL.** One opening is one
cart, and a cart is either built or it is not; `PullStatus.PARTIAL` is the *aggregate* reading over a
set of openings and is derived per pull, never stored (#343, `get_pull_staging_summaries`). The enum
type has to keep the label - the derived reading uses it - so the column carries a CHECK constraint
saying which of its values are writable here. That turns a comment into something a bad write cannot
get past.

Downgrade drops both; neither has a data component, so it is exact.
"""

import sqlalchemy as sa

from alembic import op

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None

_LIVE_LEAF_INDEX = "uq_opening_items_live_leaf"
_LIVE_LEAF_WHERE = "state <> 'SHIPPED_OUT'"
_PULL_STATUS_CHECK = "ck_shop_assembly_openings_pull_status_binary"
_PULL_STATUS_CONDITION = "pull_status IN ('NOT_PULLED', 'PULLED')"


def upgrade() -> None:
    conn = op.get_bind()

    duplicates = conn.execute(
        sa.text(
            f"""
            SELECT project_id, opening_id, coalesce(leaf, 0) AS leaf_key, count(*) AS n
              FROM opening_items
             WHERE {_LIVE_LEAF_WHERE}
             GROUP BY project_id, opening_id, coalesce(leaf, 0)
            HAVING count(*) > 1
             ORDER BY n DESC
             LIMIT 20
            """
        )
    ).all()
    if duplicates:
        offenders = "; ".join(
            f"project {r.project_id} opening {r.opening_id} leaf {r.leaf_key}: {r.n} rows" for r in duplicates
        )
        raise RuntimeError(
            "Cannot add uq_opening_items_live_leaf: more than one live assembled unit already exists "
            f"for the same door leaf. Resolve these by hand first (up to 20 shown): {offenders}"
        )

    partials = conn.execute(
        sa.text(f"SELECT count(*) FROM shop_assembly_openings WHERE NOT ({_PULL_STATUS_CONDITION})")
    ).scalar_one()
    if partials:
        raise RuntimeError(
            f"Cannot add {_PULL_STATUS_CHECK}: {partials} shop_assembly_openings row(s) hold a "
            "pull_status other than NOT_PULLED / PULLED. PARTIAL is an aggregate reading and was "
            "never meant to be stored - set those rows to NOT_PULLED or PULLED first."
        )

    op.create_index(
        _LIVE_LEAF_INDEX,
        "opening_items",
        ["project_id", "opening_id", sa.text("coalesce(leaf, 0)")],
        unique=True,
        postgresql_where=sa.text(_LIVE_LEAF_WHERE),
    )
    op.create_check_constraint(_PULL_STATUS_CHECK, "shop_assembly_openings", _PULL_STATUS_CONDITION)


def downgrade() -> None:
    op.drop_constraint(_PULL_STATUS_CHECK, "shop_assembly_openings", type_="check")
    op.drop_index(_LIVE_LEAF_INDEX, table_name="opening_items")
