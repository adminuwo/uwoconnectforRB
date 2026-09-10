from ..repositories.system_repository import SystemRepository
from ..models import AuditLog, Client

class AdminService:
    @staticmethod
    def log_admin_action(request, instance, module, action, before_value=None, after_value=None):
        auth_data = getattr(request, 'auth', None)
        impersonator_username = None
        if auth_data:
            try:
                impersonator_username = auth_data.get('impersonator_username')
            except AttributeError:
                if hasattr(auth_data, 'payload'):
                    impersonator_username = auth_data.payload.get('impersonator_username')
                elif isinstance(auth_data, dict):
                    impersonator_username = auth_data.get('impersonator_username')
                    
        if not impersonator_username and request.user.is_authenticated and request.user.role == 'ADMIN':
            impersonator_username = request.user.username
            
        if impersonator_username:
            client = getattr(instance, 'client', None)
            if not client and isinstance(instance, Client):
                client = instance
            client_name = client.business_name if client else "Global / Platform"
            
            ip_addr = request.META.get('REMOTE_ADDR')
            
            SystemRepository.create_audit_log(
                admin_name=impersonator_username,
                client_name=client_name,
                module=module,
                action=action,
                before_value=before_value,
                after_value=after_value,
                ip_address=ip_addr
            )
