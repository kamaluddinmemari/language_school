from django.core.validators import RegexValidator

# فقط حروف انگلیسی (کوچک/بزرگ)، اعداد، و کاراکترهای خاص انگلیسی مجازند — بدون فاصله و بدون حروف فارسی/یونیکد.
CREDENTIAL_REGEX = r'^[A-Za-z0-9!@#$%^&*()_+\-=\[\]{};:\'",.<>\/?~`|\\]+$'

username_validator = RegexValidator(
    regex=CREDENTIAL_REGEX,
    message='نام کاربری فقط می‌تواند شامل حروف انگلیسی (کوچک/بزرگ)، اعداد و کاراکترهای خاص انگلیسی باشد (بدون فاصله و بدون حروف فارسی).'
)

password_validator = RegexValidator(
    regex=CREDENTIAL_REGEX,
    message='رمز عبور فقط می‌تواند شامل حروف انگلیسی (کوچک/بزرگ)، اعداد و کاراکترهای خاص انگلیسی باشد (بدون فاصله و بدون حروف فارسی).'
)
