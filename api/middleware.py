from django.utils.decorators import sync_and_async_middleware
import asyncio

@sync_and_async_middleware
def SecurityAntiCacheMiddleware(get_response):
    """
    Middleware to enforce HTTP Anti-Caching headers on all API endpoints.
    Satisfies Google CASA Level 1 (ASVS L1) and SOC 2 Type 1 (CC6.1) requirements
    by ensuring sensitive tenant data is never cached by browser or intermediate proxies.
    Supports both WSGI and ASGI cleanly to prevent CancelledError thread shielding issues.
    """
    if asyncio.iscoroutinefunction(get_response):
        async def middleware(request):
            try:
                response = await get_response(request)
            except asyncio.CancelledError:
                raise
            if request.path.startswith('/api/') or request.path.startswith('/webhook/'):
                response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private, max-age=0'
                response['Pragma'] = 'no-cache'
                response['Expires'] = '0'
            return response
        return middleware
    else:
        def middleware(request):
            response = get_response(request)
            if request.path.startswith('/api/') or request.path.startswith('/webhook/'):
                response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private, max-age=0'
                response['Pragma'] = 'no-cache'
                response['Expires'] = '0'
            return response
        return middleware

