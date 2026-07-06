from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from accounts.models import User


class Command(BaseCommand):
    """
    وقتی فایل‌های جدید پروژه (بک‌اند) رو روی سرور کپی می‌کنید، این دستور رو اجرا کنید تا
    همه‌ی کاربران قبلی (با هر نقشی) پاک بشن و یک مدیر تازه ساخته بشه که بلافاصله بتونید
    وارد پنل بشید. کلاس‌ها/درخواست‌ها و بقیه‌ی داده‌ها دست نمی‌خوره.

    نمونه‌ی استفاده:
        python manage.py reset_admin --username admin --phone 09120000000 --password YOUR_PASSWORD

    اگه رمز داده نشه، از شما توی ترمینال پرسیده می‌شه (نمایش داده نمی‌شه).
    """
    help = 'همه‌ی کاربران رو پاک می‌کنه و یک مدیر تازه می‌سازه (برای بعد از کپی فایل‌های جدید)'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='admin', help='نام کاربری مدیر جدید (پیش‌فرض: admin)')
        parser.add_argument('--phone', default='09120000000', help='شماره موبایل مدیر جدید')
        parser.add_argument('--first-name', default='مدیر', help='نام')
        parser.add_argument('--last-name', default='آموزشگاه', help='نام خانوادگی')
        parser.add_argument('--password', default=None, help='رمز عبور (اگه ندید، ازتون پرسیده می‌شه)')
        parser.add_argument('--yes', action='store_true', help='بدون تایید دستی، مستقیم اجرا کن')

    def handle(self, *args, **options):
        count = User.objects.count()
        if not options['yes']:
            confirm = input(
                f'{count} کاربر (همه‌ی نقش‌ها: مدیر/معلم/دانش‌آموز) پاک می‌شن و یک مدیر تازه ساخته می‌شه. ادامه می‌دید؟ (yes/no): '
            )
            if confirm.strip().lower() not in ('yes', 'y'):
                self.stdout.write(self.style.WARNING('لغو شد.'))
                return

        password = options['password']
        if not password:
            import getpass
            password = getpass.getpass('رمز عبور مدیر جدید رو وارد کنید: ')
            password_confirm = getpass.getpass('تکرار رمز عبور: ')
            if password != password_confirm:
                raise CommandError('رمزها با هم مطابقت نداشتن.')
        if not password:
            raise CommandError('رمز عبور نمی‌تونه خالی باشه.')

        with transaction.atomic():
            deleted_count, _ = User.objects.all().delete()
            admin = User.objects.create_superuser(
                username=options['username'],
                phone=options['phone'],
                first_name=options['first_name'],
                last_name=options['last_name'],
                password=password,
            )
            admin.role = User.Role.ADMIN
            admin.save()

        self.stdout.write(self.style.SUCCESS(
            f'{deleted_count} کاربر قبلی پاک شد. مدیر تازه با نام کاربری "{admin.username}" ساخته شد — می‌تونید وارد پنل بشید.'
        ))
