from .models import Notification


def send_notification(sender, recipients, title, body, notif_type='general'):
    recipients = [r for r in recipients if r is not None]
    if not recipients:
        return
    notif = Notification.objects.create(
        sender=sender,
        title=title,
        body=body,
        notif_type=notif_type
    )
    notif.recipients.set(recipients)


def send_web_push_to_roles(roles, title, body, url='/'):
    """
    یک اعلان ناتیو صدادار (Web Push) به تمام مرورگرهای ثبت‌شده‌ی کاربرانی با نقش‌های داده‌شده
    می‌فرستد — حتی وقتی پنل بسته است. اگر مرورگری اشتراکش منقضی/باطل شده باشد (کد ۴۰۴/۴۱۰)،
    خودکار از دیتابیس پاک می‌شود تا دفعه‌ی بعد دیگر تلاش نشود.
    """
    import json
    import logging
    from django.conf import settings
    from .models import WebPushSubscription

    logger = logging.getLogger(__name__)
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.warning('pywebpush نصب نیست — ارسال Web Push نادیده گرفته شد (pip install pywebpush)')
        return

    subscriptions = WebPushSubscription.objects.filter(user__role__in=roles)
    payload = json.dumps({'title': title, 'body': body, 'url': url})
    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    'endpoint': sub.endpoint,
                    'keys': {'p256dh': sub.p256dh, 'auth': sub.auth},
                },
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={'sub': settings.VAPID_CLAIM_EMAIL},
            )
        except WebPushException as ex:
            status_code = getattr(ex.response, 'status_code', None)
            if status_code in (404, 410):
                sub.delete()  # اشتراک دیگر معتبر نیست (کاربر مرورگرش را عوض کرده یا اجازه را برداشته)
            else:
                logger.warning('ارسال Web Push ناموفق: %s', ex)
        except Exception as ex:
            logger.warning('خطای غیرمنتظره در ارسال Web Push: %s', ex)
