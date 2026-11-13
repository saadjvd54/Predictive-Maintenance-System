"""signal_thresholds

Revision ID: 0003_signal_thresholds
Revises: 0002_retention_and_aggregates
Create Date: 2026-11-13 19:15:00.000000

PharmaPredict AI — Phase 3 Step 3.2: Additive migration for equipment signal operational thresholds.
Preserves all existing tables and data.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0003_signal_thresholds'
down_revision = '0002_retention_and_aggregates'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'signal_thresholds',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('machine_id', sa.String(length=36), nullable=False),
        sa.Column('signal_id', sa.String(length=36), nullable=False),
        sa.Column('warning_min', sa.Float(), nullable=True),
        sa.Column('warning_max', sa.Float(), nullable=True),
        sa.Column('critical_min', sa.Float(), nullable=True),
        sa.Column('critical_max', sa.Float(), nullable=True),
        sa.Column('unit', sa.String(length=50), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by_user_id', sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(['machine_id'], ['machines.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['signal_id'], ['machine_signals.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('signal_id', name='uq_signal_thresholds_signal_id')
    )
    op.create_index('ix_signal_thresholds_org_id', 'signal_thresholds', ['organization_id'])
    op.create_index('ix_signal_thresholds_machine_id', 'signal_thresholds', ['machine_id'])
    op.create_index('ix_signal_thresholds_signal_id', 'signal_thresholds', ['signal_id'])
    op.create_index('ix_thresholds_mach_sig', 'signal_thresholds', ['machine_id', 'signal_id'])


def downgrade():
    op.drop_index('ix_thresholds_mach_sig', table_name='signal_thresholds')
    op.drop_index('ix_signal_thresholds_signal_id', table_name='signal_thresholds')
    op.drop_index('ix_signal_thresholds_machine_id', table_name='signal_thresholds')
    op.drop_index('ix_signal_thresholds_org_id', table_name='signal_thresholds')
    op.drop_table('signal_thresholds')

