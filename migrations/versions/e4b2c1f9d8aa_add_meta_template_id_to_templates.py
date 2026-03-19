"""add meta template id to templates

Revision ID: e4b2c1f9d8aa
Revises: 2c30e4a61ed5
Create Date: 2026-03-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e4b2c1f9d8aa'
down_revision = '2c30e4a61ed5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('meta_template_id', sa.String(length=128), nullable=True))
        batch_op.create_index(batch_op.f('ix_templates_meta_template_id'), ['meta_template_id'], unique=False)


def downgrade():
    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_templates_meta_template_id'))
        batch_op.drop_column('meta_template_id')
