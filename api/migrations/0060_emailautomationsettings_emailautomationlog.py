# Generated manually for Email Automation Settings & Decision Log
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0059_knowledgechunk_content_hash_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailAutomationSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_enabled', models.BooleanField(default=True)),
                ('allowed_senders', models.JSONField(blank=True, default=list)),
                ('excluded_senders', models.JSONField(blank=True, default=list)),
                ('allowed_domains', models.JSONField(blank=True, default=list)),
                ('excluded_domains', models.JSONField(blank=True, default=list)),
                ('auto_reply_business_inquiry', models.BooleanField(default=True)),
                ('auto_reply_customer_support', models.BooleanField(default=True)),
                ('auto_reply_sales_inquiry', models.BooleanField(default=True)),
                ('auto_reply_advertisement', models.BooleanField(default=False)),
                ('auto_reply_newsletter', models.BooleanField(default=False)),
                ('auto_reply_promotion', models.BooleanField(default=False)),
                ('auto_reply_notification', models.BooleanField(default=False)),
                ('auto_reply_spam', models.BooleanField(default=False)),
                ('include_keywords', models.JSONField(blank=True, default=list)),
                ('exclude_keywords', models.JSONField(blank=True, default=list)),
                ('allowlist_mode', models.BooleanField(default=False)),
                ('uncertain_fallback', models.CharField(choices=[('skip', 'Skip Automation (Safe Default)'), ('require_review', 'Require Review / Pending Review')], default='skip', max_length=30)),
                ('reply_to_threads', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('account', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='automation_settings', to='api.emailaccount')),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='email_automation_settings', to='api.client')),
            ],
            options={
                'ordering': ['-updated_at'],
            },
        ),
        migrations.CreateModel(
            name='EmailAutomationLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(default='gmail', max_length=30)),
                ('provider_message_id', models.CharField(db_index=True, max_length=255)),
                ('idempotency_key', models.CharField(db_index=True, max_length=255, unique=True)),
                ('sender_email', models.CharField(max_length=255)),
                ('sender_name', models.CharField(blank=True, default='', max_length=255)),
                ('subject', models.CharField(blank=True, default='', max_length=500)),
                ('mailbox', models.CharField(blank=True, default='', max_length=255)),
                ('category', models.CharField(choices=[('business_inquiry', 'Business Inquiry'), ('customer_support', 'Customer Support'), ('sales_inquiry', 'Sales Inquiry'), ('advertisement', 'Advertisement'), ('newsletter', 'Newsletter'), ('promotion', 'Promotional'), ('notification', 'Automated Notification'), ('spam', 'Spam / Phishing'), ('uncertain', 'Uncertain / Ambiguous')], default='uncertain', max_length=50)),
                ('confidence_score', models.FloatField(default=0.0)),
                ('classification_details', models.JSONField(blank=True, default=dict)),
                ('decision', models.CharField(choices=[('replied', 'Replied'), ('skipped', 'Skipped'), ('pending_review', 'Pending Review'), ('failed', 'Failed'), ('processing', 'Processing')], db_index=True, default='skipped', max_length=30)),
                ('reason', models.TextField(blank=True, default='')),
                ('reply_status', models.CharField(default='none', max_length=30)),
                ('replied_at', models.DateTimeField(blank=True, null=True)),
                ('error_message', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('account', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='automation_logs', to='api.emailaccount')),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='email_automation_logs', to='api.client')),
                ('incoming_message', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='automation_logs', to='api.emailmessage')),
                ('reply_message', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='generated_reply_logs', to='api.emailmessage')),
                ('rule_applied', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='applied_logs', to='api.emailautoreplyrule')),
                ('workflow_applied', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='applied_logs', to='api.emailautomationworkflow')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
