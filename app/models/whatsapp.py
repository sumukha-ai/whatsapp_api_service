"""Models for WhatsApp messaging domain entities."""
from app.models import db
from app.utils.datetime_utils import ist_now


class Contact(db.Model):
    __tablename__ = 'contacts'

    id = db.Column(db.Integer, primary_key=True)
    waba_account_id = db.Column(db.Integer, db.ForeignKey('waba_accounts.id'), nullable=True, index=True)
    phone_number = db.Column(db.String(32), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=True)
    opt_in_status = db.Column(db.Boolean, nullable=False, default=False)
    opt_in_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=ist_now)


class Conversation(db.Model):
    __tablename__ = 'conversations'

    id = db.Column(db.Integer, primary_key=True)
    waba_account_id = db.Column(db.Integer, db.ForeignKey('waba_accounts.id'), nullable=True, index=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id'), nullable=False, index=True)
    status = db.Column(db.String(32), nullable=False, default='open', index=True)
    session_expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=ist_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=ist_now, onupdate=ist_now)


class Template(db.Model):
    __tablename__ = 'templates'

    id = db.Column(db.Integer, primary_key=True)
    waba_account_id = db.Column(db.Integer, db.ForeignKey('waba_accounts.id'), nullable=True, index=True)
    waba_id = db.Column(db.String(128), nullable=False, index=True)
    meta_template_id = db.Column(db.String(128), nullable=True, index=True)
    template_name = db.Column(db.String(255), nullable=False, index=True)
    category = db.Column(db.String(64), nullable=True)
    language = db.Column(db.String(32), nullable=False)
    status = db.Column(db.String(32), nullable=True)
    header_type = db.Column(db.String(32), nullable=True)
    header_content = db.Column(db.Text, nullable=True)
    body_text = db.Column(db.Text, nullable=False)
    footer_text = db.Column(db.Text, nullable=True)
    buttons = db.Column(db.JSON, nullable=True)


class Message(db.Model):
    __tablename__ = 'messages'

    id = db.Column(db.Integer, primary_key=True)
    waba_account_id = db.Column(db.Integer, db.ForeignKey('waba_accounts.id'), nullable=True, index=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id'), nullable=False, index=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id'), nullable=False, index=True)
    wamid = db.Column(db.String(191), unique=True, nullable=True, index=True)
    direction = db.Column(db.String(16), nullable=False, index=True)
    type = db.Column(db.String(32), nullable=False, index=True)
    body = db.Column(db.Text, nullable=True)
    media_url = db.Column(db.Text, nullable=True)
    template_id = db.Column(db.Integer, db.ForeignKey('templates.id'), nullable=True, index=True)
    status = db.Column(db.String(32), nullable=True, index=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)


class WabaAccount(db.Model):
    __tablename__ = 'waba_accounts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    label = db.Column(db.String(255), nullable=False)
    phone_number_id = db.Column(db.String(128), unique=True, nullable=False, index=True)
    waba_id = db.Column(db.String(128), nullable=False, index=True)
    access_token = db.Column(db.Text, nullable=False)
    webhook_verify_token = db.Column(db.String(255), nullable=False)
    token_expires_at = db.Column(db.DateTime, nullable=True)


class WebhookLog(db.Model):
    __tablename__ = 'webhooks_log'

    id = db.Column(db.Integer, primary_key=True)
    waba_account_id = db.Column(db.Integer, db.ForeignKey('waba_accounts.id'), nullable=True, index=True)
    payload = db.Column(db.JSON, nullable=False)
    processed = db.Column(db.Boolean, nullable=False, default=False, index=True)
    received_at = db.Column(db.DateTime, nullable=False, default=ist_now)
    processed_at = db.Column(db.DateTime, nullable=True)


class Group(db.Model):
    __tablename__ = 'groups'

    id = db.Column(db.Integer, primary_key=True)
    waba_account_id = db.Column(db.Integer, db.ForeignKey('waba_accounts.id'), nullable=True, index=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=ist_now)


class GroupContact(db.Model):
    __tablename__ = 'group_contacts'

    id = db.Column(db.Integer, primary_key=True)
    waba_account_id = db.Column(db.Integer, db.ForeignKey('waba_accounts.id'), nullable=True, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False, index=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id'), nullable=False, index=True)
    added_at = db.Column(db.DateTime, nullable=False, default=ist_now)

    __table_args__ = (
        db.UniqueConstraint('group_id', 'contact_id', name='uq_group_contacts_group_contact'),
    )


class GroupMessage(db.Model):
    __tablename__ = 'group_messages'

    id = db.Column(db.Integer, primary_key=True)
    waba_account_id = db.Column(db.Integer, db.ForeignKey('waba_accounts.id'), nullable=True, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False, index=True)
    message_type = db.Column(db.String(32), nullable=False, index=True)
    body = db.Column(db.Text, nullable=True)
    template_payload = db.Column(db.JSON, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=ist_now, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=ist_now, onupdate=ist_now)


class GroupMessageRecipient(db.Model):
    __tablename__ = 'group_message_recipients'

    id = db.Column(db.Integer, primary_key=True)
    waba_account_id = db.Column(db.Integer, db.ForeignKey('waba_accounts.id'), nullable=True, index=True)
    group_message_id = db.Column(db.Integer, db.ForeignKey('group_messages.id'), nullable=False, index=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id'), nullable=False, index=True)
    provider_message_id = db.Column(db.String(191), nullable=True, index=True)
    status = db.Column(db.String(32), nullable=False, default='queued', index=True)
    error_code = db.Column(db.String(64), nullable=True)
    error_text = db.Column(db.Text, nullable=True)
    queued_at = db.Column(db.DateTime, nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    failed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=ist_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=ist_now, onupdate=ist_now)
