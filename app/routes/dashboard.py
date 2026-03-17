"""Dashboard analytics route aggregating WhatsApp metrics."""
from datetime import date, datetime, time, timedelta

from flask import Blueprint, jsonify
from sqlalchemy import and_, case, func

from app.database import db
from app.models.whatsapp import (
    Contact,
    Conversation,
    Group,
    GroupMessage,
    GroupMessageRecipient,
    Message,
    Template,
    WabaAccount,
    WebhookLog,
)
from app.utils.datetime_utils import ist_now
from app.utils.protected_routes import token_required

dashboard_bp = Blueprint("dashboard", __name__)


def _start_of_day(day_value):
    return datetime.combine(day_value, time.min)


def _rate(numerator, denominator):
    if not denominator:
        return 0
    return round((numerator / denominator) * 100, 1)


def _avg(values):
    if not values:
        return 0
    return round(sum(values) / len(values), 1)


def _format_duration(seconds_value):
    if seconds_value <= 0:
        return "0m 0s"

    total_seconds = int(seconds_value)
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}m {seconds}s"


def _accumulate_by_date(target, rows, key):
    for day, count in rows:
        if day is None:
            continue

        day_key = str(day)
        if day_key in target:
            target[day_key][key] += int(count or 0)


def _empty_dashboard_payload(today):
    day_keys = [(today - timedelta(days=29 - i)).isoformat() for i in range(30)]
    return {
        "overview": {
            "totalContacts": 0,
            "totalContactsDelta": 0,
            "totalGroups": 0,
            "activeGroups": 0,
            "messagesSentToday": 0,
            "messagesSentMonth": 0,
            "deliveredCount": 0,
            "readCount": 0,
            "deliveryRate": 0,
            "readRate": 0,
            "activeConversations": 0,
            "templatesSentMonth": 0,
        },
        "messageAnalytics": {
            "timeSeries": [
                {"date": day_key, "sent": 0, "delivered": 0, "read": 0, "failed": 0}
                for day_key in day_keys
            ],
            "totalSent": 0,
            "totalDelivered": 0,
            "totalRead": 0,
            "totalFailed": 0,
            "failureBreakdown": [],
        },
        "templatePerformance": [],
        "conversationBreakdown": {
            "userInitiated": 0,
            "businessInitiated": {"marketing": 0, "utility": 0, "authentication": 0},
            "freeConversations": 0,
            "billableConversations": 0,
            "avgConversationLength": 0,
            "avgResponseTime": "0m 0s",
        },
        "contactStats": {
            "total": 0,
            "optedIn": 0,
            "optedOut": 0,
            "invalid": 0,
            "newThisWeek": 0,
        },
        "health": {
            "qualityRating": "GREEN",
            "messagingLimitTier": "1K",
            "spamBlockRate": 0,
            "webhookStatus": "DEGRADED",
            "accountStatus": "DISCONNECTED",
        },
    }


def _get_user_waba_account(user_id):
    return (
        WabaAccount.query
        .filter(WabaAccount.user_id == user_id)
        .order_by(WabaAccount.id.desc())
        .first()
    )


@dashboard_bp.route("/dashboard", methods=["GET"])
@token_required
def get_dashboard(decoded):
    user_id = decoded.get("sub")
    now = ist_now()
    today = now.date()
    waba_account = _get_user_waba_account(user_id)

    if waba_account is None:
        return jsonify({"success": True, "data": _empty_dashboard_payload(today)}), 200

    waba_account_id = waba_account.id
    tomorrow = today + timedelta(days=1)
    month_start = today.replace(day=1)
    week_start = today - timedelta(days=6)
    days_30_start = today - timedelta(days=29)

    today_start_dt = _start_of_day(today)
    tomorrow_start_dt = _start_of_day(tomorrow)
    month_start_dt = _start_of_day(month_start)
    week_start_dt = _start_of_day(week_start)
    days_30_start_dt = _start_of_day(days_30_start)

    total_contacts = Contact.query.filter(Contact.waba_account_id == waba_account_id).count()
    total_contacts_delta = Contact.query.filter(
        and_(
            Contact.waba_account_id == waba_account_id,
            Contact.created_at >= week_start_dt,
            Contact.created_at < tomorrow_start_dt,
        )
    ).count()
    opted_in_count = Contact.query.filter(
        and_(Contact.waba_account_id == waba_account_id, Contact.opt_in_status.is_(True))
    ).count()
    opted_out_count = max(total_contacts - opted_in_count, 0)

    total_groups = Group.query.filter(Group.waba_account_id == waba_account_id).count()
    active_groups = db.session.query(func.count(func.distinct(GroupMessage.group_id))).filter(
        and_(
            GroupMessage.waba_account_id == waba_account_id,
            GroupMessage.created_at >= week_start_dt,
            GroupMessage.created_at < tomorrow_start_dt,
        )
    ).scalar() or 0

    group_sent_expr = func.coalesce(
        GroupMessageRecipient.sent_at,
        GroupMessageRecipient.queued_at,
        GroupMessageRecipient.created_at,
    )

    outbound_message_today = Message.query.filter(
        and_(
            Message.waba_account_id == waba_account_id,
            Message.direction == "outbound",
            Message.sent_at >= today_start_dt,
            Message.sent_at < tomorrow_start_dt,
        )
    ).count()
    group_outbound_today = GroupMessageRecipient.query.filter(
        and_(
            GroupMessageRecipient.waba_account_id == waba_account_id,
            group_sent_expr >= today_start_dt,
            group_sent_expr < tomorrow_start_dt,
        )
    ).count()
    messages_sent_today = outbound_message_today + group_outbound_today

    outbound_message_month = Message.query.filter(
        and_(
            Message.waba_account_id == waba_account_id,
            Message.direction == "outbound",
            Message.sent_at >= month_start_dt,
            Message.sent_at < tomorrow_start_dt,
        )
    ).count()
    group_outbound_month = GroupMessageRecipient.query.filter(
        and_(
            GroupMessageRecipient.waba_account_id == waba_account_id,
            group_sent_expr >= month_start_dt,
            group_sent_expr < tomorrow_start_dt,
        )
    ).count()
    messages_sent_month = outbound_message_month + group_outbound_month

    delivered_count = Message.query.filter(
        and_(
            Message.waba_account_id == waba_account_id,
            Message.delivered_at >= month_start_dt,
            Message.delivered_at < tomorrow_start_dt,
        )
    ).count() + GroupMessageRecipient.query.filter(
        and_(
            GroupMessageRecipient.waba_account_id == waba_account_id,
            GroupMessageRecipient.delivered_at >= month_start_dt,
            GroupMessageRecipient.delivered_at < tomorrow_start_dt,
        )
    ).count()

    read_count = Message.query.filter(
        and_(
            Message.waba_account_id == waba_account_id,
            Message.read_at >= month_start_dt,
            Message.read_at < tomorrow_start_dt,
        )
    ).count() + GroupMessageRecipient.query.filter(
        and_(
            GroupMessageRecipient.waba_account_id == waba_account_id,
            GroupMessageRecipient.read_at >= month_start_dt,
            GroupMessageRecipient.read_at < tomorrow_start_dt,
        )
    ).count()

    total_failed = Message.query.filter(
        and_(
            Message.waba_account_id == waba_account_id,
            Message.status == "failed",
            Message.sent_at >= month_start_dt,
            Message.sent_at < tomorrow_start_dt,
        )
    ).count() + GroupMessageRecipient.query.filter(
        and_(
            GroupMessageRecipient.waba_account_id == waba_account_id,
            GroupMessageRecipient.status == "failed",
            func.coalesce(GroupMessageRecipient.failed_at, GroupMessageRecipient.updated_at)
            >= month_start_dt,
            func.coalesce(GroupMessageRecipient.failed_at, GroupMessageRecipient.updated_at)
            < tomorrow_start_dt,
        )
    ).count()

    active_conversations = Conversation.query.filter(
        and_(
            Conversation.waba_account_id == waba_account_id,
            Conversation.status == "open",
        )
    ).count()

    templates_sent_month = Message.query.filter(
        and_(
            Message.waba_account_id == waba_account_id,
            Message.direction == "outbound",
            Message.type == "template",
            Message.sent_at >= month_start_dt,
            Message.sent_at < tomorrow_start_dt,
        )
    ).count() + db.session.query(func.count(GroupMessageRecipient.id)).join(
        GroupMessage,
        GroupMessage.id == GroupMessageRecipient.group_message_id,
    ).filter(
        and_(
            GroupMessageRecipient.waba_account_id == waba_account_id,
            GroupMessage.message_type == "template",
            GroupMessage.created_at >= month_start_dt,
            GroupMessage.created_at < tomorrow_start_dt,
        )
    ).scalar() or 0

    delivery_rate = _rate(delivered_count, messages_sent_month)
    read_rate = _rate(read_count, delivered_count)

    day_keys = [(days_30_start + timedelta(days=i)).isoformat() for i in range(30)]
    time_series_map = {
        day_key: {"date": day_key, "sent": 0, "delivered": 0, "read": 0, "failed": 0}
        for day_key in day_keys
    }

    message_sent_daily = db.session.query(
        func.date(Message.sent_at),
        func.count(Message.id),
    ).filter(
        and_(
            Message.waba_account_id == waba_account_id,
            Message.direction == "outbound",
            Message.sent_at >= days_30_start_dt,
            Message.sent_at < tomorrow_start_dt,
        )
    ).group_by(func.date(Message.sent_at)).all()

    group_sent_daily = db.session.query(
        func.date(group_sent_expr),
        func.count(GroupMessageRecipient.id),
    ).filter(
        and_(
            GroupMessageRecipient.waba_account_id == waba_account_id,
            group_sent_expr >= days_30_start_dt,
            group_sent_expr < tomorrow_start_dt,
        )
    ).group_by(func.date(group_sent_expr)).all()

    delivered_daily = db.session.query(
        func.date(Message.delivered_at),
        func.count(Message.id),
    ).filter(
        and_(
            Message.waba_account_id == waba_account_id,
            Message.delivered_at >= days_30_start_dt,
            Message.delivered_at < tomorrow_start_dt,
        )
    ).group_by(func.date(Message.delivered_at)).all()

    group_delivered_daily = db.session.query(
        func.date(GroupMessageRecipient.delivered_at),
        func.count(GroupMessageRecipient.id),
    ).filter(
        and_(
            GroupMessageRecipient.waba_account_id == waba_account_id,
            GroupMessageRecipient.delivered_at >= days_30_start_dt,
            GroupMessageRecipient.delivered_at < tomorrow_start_dt,
        )
    ).group_by(func.date(GroupMessageRecipient.delivered_at)).all()

    read_daily = db.session.query(
        func.date(Message.read_at),
        func.count(Message.id),
    ).filter(
        and_(
            Message.waba_account_id == waba_account_id,
            Message.read_at >= days_30_start_dt,
            Message.read_at < tomorrow_start_dt,
        )
    ).group_by(func.date(Message.read_at)).all()

    group_read_daily = db.session.query(
        func.date(GroupMessageRecipient.read_at),
        func.count(GroupMessageRecipient.id),
    ).filter(
        and_(
            GroupMessageRecipient.waba_account_id == waba_account_id,
            GroupMessageRecipient.read_at >= days_30_start_dt,
            GroupMessageRecipient.read_at < tomorrow_start_dt,
        )
    ).group_by(func.date(GroupMessageRecipient.read_at)).all()

    failed_daily = db.session.query(
        func.date(Message.sent_at),
        func.count(Message.id),
    ).filter(
        and_(
            Message.waba_account_id == waba_account_id,
            Message.status == "failed",
            Message.sent_at >= days_30_start_dt,
            Message.sent_at < tomorrow_start_dt,
        )
    ).group_by(func.date(Message.sent_at)).all()

    group_failed_daily = db.session.query(
        func.date(func.coalesce(GroupMessageRecipient.failed_at, GroupMessageRecipient.updated_at)),
        func.count(GroupMessageRecipient.id),
    ).filter(
        and_(
            GroupMessageRecipient.waba_account_id == waba_account_id,
            GroupMessageRecipient.status == "failed",
            func.coalesce(GroupMessageRecipient.failed_at, GroupMessageRecipient.updated_at)
            >= days_30_start_dt,
            func.coalesce(GroupMessageRecipient.failed_at, GroupMessageRecipient.updated_at)
            < tomorrow_start_dt,
        )
    ).group_by(
        func.date(func.coalesce(GroupMessageRecipient.failed_at, GroupMessageRecipient.updated_at))
    ).all()

    _accumulate_by_date(time_series_map, message_sent_daily, "sent")
    _accumulate_by_date(time_series_map, group_sent_daily, "sent")
    _accumulate_by_date(time_series_map, delivered_daily, "delivered")
    _accumulate_by_date(time_series_map, group_delivered_daily, "delivered")
    _accumulate_by_date(time_series_map, read_daily, "read")
    _accumulate_by_date(time_series_map, group_read_daily, "read")
    _accumulate_by_date(time_series_map, failed_daily, "failed")
    _accumulate_by_date(time_series_map, group_failed_daily, "failed")

    failure_reason_rows = db.session.query(
        func.coalesce(GroupMessageRecipient.error_text, GroupMessageRecipient.error_code, "Unknown"),
        func.count(GroupMessageRecipient.id),
    ).filter(
        and_(
            GroupMessageRecipient.waba_account_id == waba_account_id,
            GroupMessageRecipient.status == "failed",
            func.coalesce(GroupMessageRecipient.failed_at, GroupMessageRecipient.updated_at)
            >= month_start_dt,
            func.coalesce(GroupMessageRecipient.failed_at, GroupMessageRecipient.updated_at)
            < tomorrow_start_dt,
        )
    ).group_by(
        func.coalesce(GroupMessageRecipient.error_text, GroupMessageRecipient.error_code, "Unknown")
    ).all()

    failure_breakdown = [
        {"reason": reason, "count": int(count)} for reason, count in failure_reason_rows
    ]

    unidentified_failed = Message.query.filter(
        and_(
            Message.waba_account_id == waba_account_id,
            Message.status == "failed",
            Message.sent_at >= month_start_dt,
            Message.sent_at < tomorrow_start_dt,
        )
    ).count()
    if unidentified_failed:
        failure_breakdown.append({"reason": "Unknown", "count": int(unidentified_failed)})

    template_rows = Template.query.filter(
        Template.waba_account_id == waba_account_id
    ).order_by(Template.id.asc()).all()

    template_performance = []
    for template in template_rows:
        template_sent = Message.query.filter(
            and_(
                Message.waba_account_id == waba_account_id,
                Message.template_id == template.id,
                Message.direction == "outbound",
                Message.sent_at >= month_start_dt,
                Message.sent_at < tomorrow_start_dt,
            )
        ).count()
        template_delivered = Message.query.filter(
            and_(
                Message.waba_account_id == waba_account_id,
                Message.template_id == template.id,
                Message.delivered_at >= month_start_dt,
                Message.delivered_at < tomorrow_start_dt,
            )
        ).count()
        template_read = Message.query.filter(
            and_(
                Message.waba_account_id == waba_account_id,
                Message.template_id == template.id,
                Message.read_at >= month_start_dt,
                Message.read_at < tomorrow_start_dt,
            )
        ).count()

        template_performance.append(
            {
                "id": f"tpl_{template.id:03d}",
                "name": template.template_name,
                "category": (template.category or "").upper() or None,
                "status": (template.status or "").upper() or None,
                "language": template.language,
                "sent": int(template_sent),
                "delivered": int(template_delivered),
                "read": int(template_read),
                "deliveryRate": _rate(template_delivered, template_sent),
                "readRate": _rate(template_read, template_delivered),
                "ctr": None,
            }
        )

    inbound_conversation_count = db.session.query(func.count(func.distinct(Message.conversation_id))).filter(
        and_(
            Message.waba_account_id == waba_account_id,
            Message.direction == "inbound",
            Message.sent_at >= month_start_dt,
            Message.sent_at < tomorrow_start_dt,
        )
    ).scalar() or 0

    category_rows = db.session.query(
        func.lower(Template.category),
        func.count(Message.id),
    ).join(
        Template,
        Template.id == Message.template_id,
    ).filter(
        and_(
            Message.waba_account_id == waba_account_id,
            Message.direction == "outbound",
            Message.type == "template",
            Message.sent_at >= month_start_dt,
            Message.sent_at < tomorrow_start_dt,
        )
    ).group_by(func.lower(Template.category)).all()

    business_categories = {"marketing": 0, "utility": 0, "authentication": 0}
    for category, count in category_rows:
        key = (category or "").lower()
        if key in business_categories:
            business_categories[key] = int(count)

    business_initiated_total = sum(business_categories.values())
    free_conversations = int(inbound_conversation_count)
    billable_conversations = int(business_initiated_total)

    conversation_ids = [
        row[0]
        for row in db.session.query(Conversation.id).filter(
            and_(
                Conversation.waba_account_id == waba_account_id,
                Conversation.created_at >= days_30_start_dt,
                Conversation.created_at < tomorrow_start_dt,
            )
        ).all()
    ]

    avg_conversation_length = 0
    avg_response_time = "0m 0s"
    if conversation_ids:
        length_rows = db.session.query(
            Message.conversation_id,
            func.count(Message.id),
        ).filter(
            and_(
                Message.waba_account_id == waba_account_id,
                Message.conversation_id.in_(conversation_ids),
            )
        ).group_by(Message.conversation_id).all()
        avg_conversation_length = _avg([int(count) for _, count in length_rows])

        response_rows = db.session.query(
            Message.conversation_id,
            func.min(case((Message.direction == "inbound", Message.sent_at))),
            func.min(case((Message.direction == "outbound", Message.sent_at))),
        ).filter(
            and_(
                Message.waba_account_id == waba_account_id,
                Message.conversation_id.in_(conversation_ids),
                Message.sent_at.isnot(None),
            )
        ).group_by(Message.conversation_id).all()

        response_seconds = []
        for _, first_inbound_at, first_outbound_at in response_rows:
            if first_inbound_at and first_outbound_at and first_outbound_at >= first_inbound_at:
                response_seconds.append((first_outbound_at - first_inbound_at).total_seconds())
        avg_response_time = _format_duration(_avg(response_seconds))

    invalid_contacts = Contact.query.filter(
        and_(
            Contact.waba_account_id == waba_account_id,
            Contact.opt_in_status.is_(False),
            Contact.created_at < tomorrow_start_dt,
        )
    ).count()

    spam_failed = GroupMessageRecipient.query.filter(
        and_(
            GroupMessageRecipient.waba_account_id == waba_account_id,
            GroupMessageRecipient.status == "failed",
            func.lower(func.coalesce(GroupMessageRecipient.error_text, "")).like("%spam%"),
            func.coalesce(GroupMessageRecipient.failed_at, GroupMessageRecipient.updated_at)
            >= month_start_dt,
            func.coalesce(GroupMessageRecipient.failed_at, GroupMessageRecipient.updated_at)
            < tomorrow_start_dt,
        )
    ).count()
    spam_block_rate = _rate(spam_failed, messages_sent_month)

    quality_rating = "GREEN"
    if spam_block_rate >= 5:
        quality_rating = "RED"
    elif spam_block_rate >= 2:
        quality_rating = "YELLOW"

    messaging_limit_tier = "1K"
    if messages_sent_month >= 100000:
        messaging_limit_tier = "100K"
    elif messages_sent_month >= 10000:
        messaging_limit_tier = "10K"

    latest_webhook = WebhookLog.query.filter(
        and_(
            WebhookLog.waba_account_id == waba_account_id,
            WebhookLog.processed.is_(True),
        )
    ).order_by(WebhookLog.processed_at.desc()).first()

    webhook_status = "DEGRADED"
    if latest_webhook and latest_webhook.processed_at:
        if latest_webhook.processed_at >= (now - timedelta(hours=24)):
            webhook_status = "HEALTHY"

    account_status = "CONNECTED"
    if waba_account.token_expires_at and waba_account.token_expires_at < now:
        account_status = "TOKEN_EXPIRED"

    payload = {
        "overview": {
            "totalContacts": int(total_contacts),
            "totalContactsDelta": int(total_contacts_delta),
            "totalGroups": int(total_groups),
            "activeGroups": int(active_groups),
            "messagesSentToday": int(messages_sent_today),
            "messagesSentMonth": int(messages_sent_month),
            "deliveredCount": int(delivered_count),
            "readCount": int(read_count),
            "deliveryRate": delivery_rate,
            "readRate": read_rate,
            "activeConversations": int(active_conversations),
            "templatesSentMonth": int(templates_sent_month),
        },
        "messageAnalytics": {
            "timeSeries": [time_series_map[day_key] for day_key in day_keys],
            "totalSent": int(messages_sent_month),
            "totalDelivered": int(delivered_count),
            "totalRead": int(read_count),
            "totalFailed": int(total_failed),
            "failureBreakdown": failure_breakdown,
        },
        "templatePerformance": template_performance,
        "conversationBreakdown": {
            "userInitiated": int(inbound_conversation_count),
            "businessInitiated": business_categories,
            "freeConversations": int(free_conversations),
            "billableConversations": int(billable_conversations),
            "avgConversationLength": avg_conversation_length,
            "avgResponseTime": avg_response_time,
        },
        "contactStats": {
            "total": int(total_contacts),
            "optedIn": int(opted_in_count),
            "optedOut": int(opted_out_count),
            "invalid": int(invalid_contacts),
            "newThisWeek": int(total_contacts_delta),
        },
        "health": {
            "qualityRating": quality_rating,
            "messagingLimitTier": messaging_limit_tier,
            "spamBlockRate": spam_block_rate,
            "webhookStatus": webhook_status,
            "accountStatus": account_status,
        },
    }

    return jsonify({"success": True, "data": payload}), 200