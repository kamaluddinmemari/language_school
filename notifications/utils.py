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
