"""Preserve tracked files until an administrator explicitly purges missing entries."""
from alembic import op
import sqlalchemy as sa


revision = 'b1c2d3e4f5a6'
down_revision = 'a9b0c1d2e3f4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('files', sa.Column('missing_since', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('files', 'missing_since')
