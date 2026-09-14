from rest_framework.permissions import BasePermission

class IsApprovedUser(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.role == 'CLIENT':
            if request.user.client and request.user.client.status != 'ACTIVE':
                return False
            return request.user.status not in ['SUSPENDED', 'REJECTED']
        return True


class IsSuperAdminUser(BasePermission):
    """
    Permission check that grants access only to verified platform super administrators.
    Checks role == 'ADMIN', enterprise_role == 'SUPER_ADMIN', is_staff or is_superuser.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return bool(
            request.user.role == 'ADMIN' or
            getattr(request.user, 'enterprise_role', None) == 'SUPER_ADMIN' or
            request.user.is_staff or
            request.user.is_superuser
        )

