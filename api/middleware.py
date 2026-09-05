class SecurityAntiCacheMiddleware:
    """
    Middleware to enforce HTTP Anti-Caching headers on all API endpoints.
    Satisfies Google CASA Level 1 (ASVS L1) and SOC 2 Type 1 (CC6.1) requirements
    by ensuring sensitive tenant data is never cached by browser or intermediate proxies.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith('/api/') or request.path.startswith('/webhook/'):
            response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private, max-age=0'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
        return response
