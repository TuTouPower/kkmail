"""Create folder_patrol_status table and migrate patrol cursor state (adoption A14).

Revision ID: 20261107_0031
Revises: 20261031_0030
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261107_0031"
down_revision: Union[str, None] = "20261031_0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "folder_patrol_status",
        sa.Column(
            "folder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("folders.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("last_status", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_probe_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_probe_failures",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Migrate any existing last_status / last_probe_at / last_probe_failures from sync_checkpoints.cursor
    op.execute(
        """
        INSERT INTO folder_patrol_status (
            folder_id,
            last_status,
            last_probe_at,
            last_probe_failures,
            created_at,
            updated_at
        )
        SELECT
            folder_id,
            CASE WHEN cursor ? 'last_status' THEN cursor->'last_status' ELSE NULL END,
            CASE
                WHEN cursor ? 'last_probe_at' AND (cursor->>'last_probe_at') ~ '^-?[0-9]+(\\.[0-9]+)?$'
                THEN to_timestamp((cursor->>'last_probe_at')::double precision)
                ELSE NULL
            END,
            CASE
                WHEN cursor ? 'last_probe_failures' AND (cursor->>'last_probe_failures') ~ '^[0-9]+$'
                THEN (cursor->>'last_probe_failures')::integer
                ELSE 0
            END,
            now(),
            now()
        FROM sync_checkpoints
        WHERE cursor ? 'last_status' OR cursor ? 'last_probe_at' OR cursor ? 'last_probe_failures'
        ON CONFLICT (folder_id) DO UPDATE SET
            last_status = EXCLUDED.last_status,
            last_probe_at = EXCLUDED.last_probe_at,
            last_probe_failures = EXCLUDED.last_probe_failures,
            updated_at = EXCLUDED.updated_at;
        """
    )

    # Remove the deprecated patrol keys from sync_checkpoints.cursor
    op.execute(
        """
        UPDATE sync_checkpoints
        SET cursor = cursor - ARRAY['last_status', 'last_probe_at', 'last_probe_failures']
        WHERE cursor ? 'last_status' OR cursor ? 'last_probe_at' OR cursor ? 'last_probe_failures';
        """
    )


def downgrade() -> None:
    # Backfill folder_patrol_status data back into sync_checkpoints.cursor before dropping table
    op.execute(
        """
        UPDATE sync_checkpoints sc
        SET cursor = sc.cursor || jsonb_strip_nulls(jsonb_build_object(
            'last_status', fps.last_status,
            'last_probe_at', EXTRACT(EPOCH FROM fps.last_probe_at),
            'last_probe_failures', CASE WHEN fps.last_probe_failures > 0 THEN fps.last_probe_failures ELSE NULL END
        ))
        FROM folder_patrol_status fps
        WHERE sc.folder_id = fps.folder_id;
        """
    )
    op.drop_table("folder_patrol_status")
