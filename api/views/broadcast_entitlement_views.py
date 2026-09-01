import logging
import uuid
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from api.services.broadcast_entitlement_service import BroadcastEntitlementService

logger = logging.getLogger(__name__)

class BroadcastEntitlementSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not user.client:
            return Response({'error': 'No workspace client associated with user.'}, status=status.HTTP_400_BAD_REQUEST)

        summary = BroadcastEntitlementService.get_entitlement_summary(user.client)
        return Response(summary, status=status.HTTP_200_OK)


class BroadcastValidateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.client:
            return Response({'error': 'No workspace client associated with user.'}, status=status.HTTP_400_BAD_REQUEST)

        summary = BroadcastEntitlementService.get_entitlement_summary(user.client)
        return Response({
            'can_broadcast': summary['can_broadcast'],
            'charged_via': summary['next_broadcast_source'],
            'cost_inr': summary['next_broadcast_cost_inr'],
            'wallet_balance_inr': summary['wallet_balance_inr'],
            'remaining_included': summary['remaining_quantity']
        }, status=status.HTTP_200_OK)


class BroadcastConsumeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.client:
            return Response({'error': 'No workspace client associated with user.'}, status=status.HTTP_400_BAD_REQUEST)

        broadcast_id = request.data.get('broadcast_id') or f"brd_{uuid.uuid4().hex[:8]}"
        idempotency_key = request.data.get('idempotency_key') or f"key_{broadcast_id}_{user.client.id}"

        try:
            res = BroadcastEntitlementService.consume_or_reserve_broadcast(
                client=user.client,
                broadcast_id=broadcast_id,
                idempotency_key=idempotency_key,
                user=user
            )
            return Response(res, status=status.HTTP_200_OK)
        except ValueError as err:
            return Response({'error': str(err), 'code': 'INSUFFICIENT_FUNDS_OR_EXHAUSTED'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as err:
            logger.error(f"[BroadcastConsumeView] Unexpected Error: {err}", exc_info=True)
            return Response({'error': 'Broadcast processing failed.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class BroadcastRefundView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        broadcast_usage_id = request.data.get('broadcast_usage_id')
        reason = request.data.get('reason', 'Broadcast execution failed')

        if not broadcast_usage_id:
            return Response({'error': 'broadcast_usage_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            res = BroadcastEntitlementService.refund_failed_broadcast(
                broadcast_usage_id=int(broadcast_usage_id),
                reason=reason
            )
            return Response(res, status=status.HTTP_200_OK)
        except ValueError as err:
            return Response({'error': str(err)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as err:
            logger.error(f"[BroadcastRefundView] Error: {err}", exc_info=True)
            return Response({'error': 'Refund operation failed.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
