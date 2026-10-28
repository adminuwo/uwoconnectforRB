import sys
import os
from django.apps import AppConfig

class ApiConfig(AppConfig):
    name = 'api'

    def ready(self):
        mgmt_cmds = {'migrate', 'makemigrations', 'collectstatic', 'check', 'test', 'shell'}
        if any(cmd in sys.argv for cmd in mgmt_cmds):
            return

        is_runserver = 'runserver' in sys.argv
        is_prod_server = (
            any('daphne' in arg for arg in sys.argv)
            or any('gunicorn' in arg for arg in sys.argv)
            or any('uvicorn' in arg for arg in sys.argv)
            or 'daphne' in sys.argv[0].lower()
            or 'gunicorn' in sys.argv[0].lower()
            or bool(os.getenv('PORT'))
        )

        if is_runserver or is_prod_server:
            from django.db import connections
            try:
                db_conn = connections['default']
                db_conn.ensure_connection()
                db_name = os.getenv('MONGODB_DB_NAME', 'unknown')
                print(f"\n[OK] SUCCESS: MongoDB connection is ACTIVE! (db: {db_name})\n")
            except Exception as e:
                print(f"\n[ERROR] MongoDB connection FAILED!")
                print(f"Check your .env URL and password. Reason: {str(e)}\n")

            # Start background threads safely without blocking import locks
            # In runserver, only start in child reloader; in production (Daphne/Gunicorn), start unconditionally
            is_main_process = (os.environ.get('RUN_MAIN') == 'true' or '--noreload' in sys.argv) if is_runserver else True
            if is_main_process:
                import threading
                import time
                from django.db import close_old_connections

                def youtube_poller():
                    time.sleep(25)  # Wait for server and all imports to fully complete
                    while True:
                        try:
                            close_old_connections()
                            from api.models import Client
                            import api.views.youtube_views as ytv
                            
                            clients = Client.objects.filter(youtube_enabled=True)
                            for client in clients:
                                config = client.youtube_config or {}
                                if config.get("bot_enabled", False) and hasattr(ytv, 'auto_reply_to_youtube_comments'):
                                    ytv.auto_reply_to_youtube_comments(client)
                                if config.get("broadcast_enabled", False) and hasattr(ytv, 'check_and_broadcast_youtube_uploads'):
                                    ytv.check_and_broadcast_youtube_uploads(client)
                        except Exception as poll_err:
                            pass
                        
                        time.sleep(30)

                thread = threading.Thread(target=youtube_poller, daemon=True, name="YouTubeBackgroundPoller")
                thread.start()

                def campaign_scheduler():
                    time.sleep(30)  # Wait for server to fully complete startup
                    from django.utils import timezone
                    while True:
                        try:
                            close_old_connections()
                            from api.models import Campaign
                            from api.services.campaign_service import CampaignService
                            
                            # Find all scheduled campaigns where scheduled_at is less than or equal to now
                            now = timezone.now()
                            ready_campaigns = Campaign.objects.filter(status='SCHEDULED', scheduled_at__lte=now)
                            for campaign in ready_campaigns:
                                campaign.status = 'SENDING'
                                campaign.save()
                                
                                # Process each campaign in its own thread to avoid blocking the scheduler
                                camp_thread = threading.Thread(target=CampaignService.process_campaign, args=(campaign.id,))
                                camp_thread.start()
                        except Exception as e:
                            print(f"[Campaign Scheduler Error]: {e}")
                        
                        time.sleep(60)

                campaign_thread = threading.Thread(target=campaign_scheduler, daemon=True, name="CampaignBackgroundScheduler")
                campaign_thread.start()

                # Start Follow-up Scheduler
                from api.scheduler_followups import start_followup_scheduler
                start_followup_scheduler()
