from ..models import User, TeamInvite, PasswordResetOTP

class UserRepository:
    @staticmethod
    def get_user(id=None, email=None):
        if id: return User.objects.filter(id=id).first()
        if email: return User.objects.filter(email=email).first()
        return None

    @staticmethod
    def filter_users(**kwargs):
        return User.objects.filter(**kwargs)

    @staticmethod
    def create_user(**kwargs):
        return User.objects.create(**kwargs)

    @staticmethod
    def get_user_or_create(**kwargs):
        defaults = kwargs.pop('defaults', {})
        return User.objects.get_or_create(**kwargs, defaults=defaults)

class TeamInviteRepository:
    @staticmethod
    def filter_invites(**kwargs):
        return TeamInvite.objects.filter(**kwargs)

    @staticmethod
    def get_invite(id, client):
        return TeamInvite.objects.filter(id=id, client=client).first()

    @staticmethod
    def create_invite(**kwargs):
        return TeamInvite.objects.create(**kwargs)

class PasswordResetOTPRepository:
    @staticmethod
    def create_otp(**kwargs):
        return PasswordResetOTP.objects.create(**kwargs)
    
    @staticmethod
    def filter_otps(**kwargs):
        return PasswordResetOTP.objects.filter(**kwargs)

    @staticmethod
    def create_passwordresetotp(**kwargs):
        return PasswordResetOTP.objects.create(**kwargs)

    @staticmethod
    def filter_passwordresetotps(**kwargs):
        return PasswordResetOTP.objects.filter(**kwargs)

    @staticmethod
    def get_all_users():
        return User.objects.all()

    @staticmethod
    def get_all():
        return User.objects.all()
