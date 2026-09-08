import json
from channels.generic.websocket import AsyncWebsocketConsumer
from urllib.parse import parse_qs
import jwt
from django.conf import settings
from asgiref.sync import sync_to_async
from .models import User
from .repositories.user_repository import UserRepository

class InboxConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        query_string = self.scope['query_string'].decode()
        query_params = parse_qs(query_string)
        token = query_params.get('token', [None])[0]

        if not token:
            await self.close()
            return

        try:
            # Decode the JWT token
            decoded_data = jwt.decode(token, settings.SIMPLE_JWT['SIGNING_KEY'], algorithms=[settings.SIMPLE_JWT['ALGORITHM']])
            user_id = decoded_data.get(settings.SIMPLE_JWT['USER_ID_CLAIM'])
            
            user = await self.get_user(user_id)
            if not user or not user.client_id:
                await self.close()
                return
                
            self.user = user
            self.client_id = str(user.client_id)
            self.room_group_name = f'inbox_{self.client_id}'

            # Join room group
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )

            await self.accept()
            
            # Send initial connection success message
            await self.send(text_data=json.dumps({
                'type': 'connection_established',
                'message': 'Connected to inbox successfully',
                'user': {
                    'id': str(user.id),
                    'username': user.username,
                    'role': user.role,
                    'department': user.department
                }
            }))

        except Exception as e:
            await self.close()

    @sync_to_async
    def get_user(self, user_id):
        try:
            return UserRepository.get_user(id=user_id)
        except User.DoesNotExist:
            return None

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    # Receive message from WebSocket and broadcast to group
    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            action_type = data.get('type')

            if action_type in ['typing_status', 'view_conversation', 'takeover_event', 'transfer_event', 'lock_event', 'status_change_event', 'note_event']:
                if hasattr(self, 'user') and self.user:
                    data['sender_user_id'] = str(self.user.id)
                    data['sender_type'] = 'agent'
                # Broadcast payload to group
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'broadcast_event',
                        'event_data': data
                    }
                )
        except Exception as e:
            pass

    async def broadcast_event(self, event):
        await self.send(text_data=json.dumps(event['event_data']))

    # Receive message from room group
    async def new_message(self, event):
        message = event['message']

        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'new_message',
            'message': message
        }))

    # Forward message delivery and read receipts
    async def message_status_update(self, event):
        await self.send(text_data=json.dumps(event))

class TeamChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        query_string = self.scope['query_string'].decode()
        query_params = parse_qs(query_string)
        token = query_params.get('token', [None])[0]

        if not token:
            await self.close()
            return

        try:
            decoded_data = jwt.decode(token, settings.SIMPLE_JWT['SIGNING_KEY'], algorithms=[settings.SIMPLE_JWT['ALGORITHM']])
            user_id = decoded_data.get(settings.SIMPLE_JWT['USER_ID_CLAIM'])
            
            user = await self.get_user(user_id)
            if not user or not user.client_id:
                await self.close()
                return
                
            self.client_id = str(user.client_id)
            self.room_group_name = f'teamchat_{self.client_id}'

            # Join room group
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )

            await self.accept()

        except Exception as e:
            await self.close()

    @sync_to_async
    def get_user(self, user_id):
        try:
            return UserRepository.get_user(id=user_id)
        except User.DoesNotExist:
            return None

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    async def new_team_message(self, event):
        message = event['message']
        await self.send(text_data=json.dumps({
            'type': 'new_team_message',
            'message': message
        }))

import logging
logger = logging.getLogger(__name__)

import re

def sanitize_group_name(name):
    # Channels allows ASCII alphanumerics, hyphens, or periods.
    # We replace any other character (like '@') with an underscore.
    if not name:
        return name
    return re.sub(r'[^a-zA-Z0-9\-\.]', '_', name)

class WebRTCConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        try:
            logger.error(f"[WebRTC] Connection attempt started for scope: {self.scope.get('query_string', b'').decode()}")
            query_string = self.scope.get('query_string', b'').decode()
            query_params = parse_qs(query_string)
            token = query_params.get('token', [None])[0]

            if not token or token == 'null' or token == 'undefined':
                logger.error("[WebRTC] No valid token provided")
                await self.close()
                return

            try:
                decoded_data = jwt.decode(token, settings.SIMPLE_JWT['SIGNING_KEY'], algorithms=[settings.SIMPLE_JWT['ALGORITHM']])
                user_id = decoded_data.get(settings.SIMPLE_JWT['USER_ID_CLAIM'])
            except Exception as e:
                logger.error(f"[WebRTC] JWT Decode Error: {e}")
                await self.close()
                return
                
            user = await self.get_user(user_id)
            if not user:
                logger.error(f"[WebRTC] User {user_id} not found")
                await self.close()
                return
                
            self.user = user
            
            # Safe email/username fallback
            email = getattr(user, 'email', None) or ""
            username = getattr(user, 'username', None) or ""
            ident = email.lower() if email else username.lower()
            if not ident:
                ident = str(user_id)
                
            self.personal_group = f'webrtc_user_{sanitize_group_name(ident)}'
            
            if self.channel_layer is None:
                logger.error("[WebRTC] CHANNEL_LAYER IS NONE! Check settings.py")
                await self.close()
                return
                
            await self.channel_layer.group_add(self.personal_group, self.channel_name)

            client_id = getattr(user, 'client_id', None)
            if client_id:
                self.client_id = str(client_id)
                self.workspace_group = f'webrtc_workspace_{self.client_id}'
                await self.channel_layer.group_add(self.workspace_group, self.channel_name)

            await self.accept()
            logger.error(f"[WebRTC] Successfully connected {ident}")

        except Exception as e:
            import traceback
            logger.error(f"[WebRTC] Fatal Connect Error: {e}")
            logger.error(traceback.format_exc())
            await self.close()

    @sync_to_async
    def get_user(self, user_id):
        try:
            return UserRepository.get_user(id=user_id)
        except User.DoesNotExist:
            return None

    async def disconnect(self, close_code):
        if hasattr(self, 'workspace_group'):
            await self.channel_layer.group_discard(self.workspace_group, self.channel_name)
        if hasattr(self, 'personal_group'):
            await self.channel_layer.group_discard(self.personal_group, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            msg_type = data.get('type')
            
            target_group = None
            if msg_type in ['offer', 'answer', 'ice_candidate', 'call_ended']:
                recipient = data.get('recipient', '').lower()
                target_group = f'webrtc_user_{sanitize_group_name(recipient)}'
            
            if target_group:
                await self.channel_layer.group_send(
                    target_group,
                    {
                        'type': 'webrtc_message',
                        'message': data
                    }
                )
        except Exception as e:
            pass

    async def webrtc_message(self, event):
        message = event['message']
        await self.send(text_data=json.dumps(message))
