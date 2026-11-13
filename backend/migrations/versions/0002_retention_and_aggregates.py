"""retention_and_aggregates

Revision ID: 0002_retention_and_aggregates
Revises: 0001_initial_schema
Create Date: 2026-11-12 23:30:00.000000

PharmaPredict AI — Phase 3 Step 3.1: Additive migration for telemetry retention policies,
execution audit logs, and pre-aggregation rollup storage.
Preserves all 57 existing tables and existing data.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0002_retention_and_aggregates'
down_revision = '0001_initial_schema'
branch_labels = None
depends_on = None


def upgrade():
    # 1. retention_policies
    op.create_table(
        'retention_policies',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('machine_id', sa.String(length=36), nullable=True),
        sa.Column('raw_retention_days', sa.Integer(), nullable=False, server_default='90'),
        sa.Column('aggregate_retention_days', sa.Integer(), nullable=False, server_default='365'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('archive_before_delete', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('batch_size', sa.Integer(), nullable=False, server_default='500'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by_user_id', sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(['machine_id'], ['machines.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_retention_policies_organization_id', 'retention_policies', ['organization_id'])
    op.create_index('ix_retention_policies_machine_id', 'retention_policies', ['machine_id'])

    # 2. retention_executions
    op.create_table(
        'retention_executions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('policy_id', sa.String(length=36), nullable=True),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('machine_id', sa.String(length=36), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dry_run', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('cutoff_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('records_scanned', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('records_aggregated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('records_deleted', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('batch_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='IN_PROGRESS'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('executed_by', sa.String(length=100), nullable=False, server_default='SYSTEM'),
        sa.ForeignKeyConstraint(['policy_id'], ['retention_policies.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_retention_executions_organization_id', 'retention_executions', ['organization_id'])
    op.create_index('ix_retention_executions_machine_id', 'retention_executions', ['machine_id'])
    op.create_index('ix_retention_executions_policy_id', 'retention_executions', ['policy_id'])

    # 3. signal_reading_aggregates
    op.create_table(
        'signal_reading_aggregates',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('machine_id', sa.String(length=36), nullable=False),
        sa.Column('signal_id', sa.String(length=36), nullable=False),
        sa.Column('bucket_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('bucket_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('bucket_resolution', sa.String(length=20), nullable=False, server_default='1h'),
        sa.Column('min_value', sa.Float(), nullable=True),
        sa.Column('max_value', sa.Float(), nullable=True),
        sa.Column('avg_value', sa.Float(), nullable=True),
        sa.Column('first_value', sa.Float(), nullable=True),
        sa.Column('last_value', sa.Float(), nullable=True),
        sa.Column('reading_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('quality_summary', sa.String(length=50), nullable=False, server_default='Good'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['machine_id'], ['machines.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['signal_id'], ['machine_signals.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('signal_id', 'bucket_start', 'bucket_resolution', name='uq_signal_bucket_resolution')
    )
    op.create_index('ix_agg_machine_bucket', 'signal_reading_aggregates', ['machine_id', 'bucket_start'])
    op.create_index('ix_agg_signal_bucket', 'signal_reading_aggregates', ['signal_id', 'bucket_start'])
    op.create_index('ix_signal_reading_aggregates_org_id', 'signal_reading_aggregates', ['organization_id'])


def downgrade():
    op.drop_index('ix_signal_reading_aggregates_org_id', table_name='signal_reading_aggregates')
    op.drop_index('ix_agg_signal_bucket', table_name='signal_reading_aggregates')
    op.drop_index('ix_agg_machine_bucket', table_name='signal_reading_aggregates')
    op.drop_table('signal_reading_aggregates')

    op.drop_index('ix_retention_executions_policy_id', table_name='retention_executions')
    op.drop_index('ix_retention_executions_machine_id', table_name='retention_executions')
    op.drop_index('ix_retention_executions_organization_id', table_name='retention_executions')
    op.drop_table('retention_executions')

    op.drop_index('ix_retention_policies_machine_id', table_name='retention_policies')
    op.drop_index('ix_retention_policies_organization_id', table_name='retention_policies')
    op.drop_table('retention_policies')

