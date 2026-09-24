from django.urls import path
from . import views

urlpatterns = [
    # Authentication
    path('auth/register/', views.UserRegistrationView.as_view(), name='register'),
    path('auth/login/', views.CustomAuthToken.as_view(), name='login'),
    path('auth/logout/', views.logout_view, name='logout'),
    
    # Domain Discovery
    path('domain-discovery/initiate/', views.initiate_domain_discovery, name='initiate_domain_discovery'),
    path('domain-discovery/status/<uuid:task_id>/', views.domain_discovery_status, name='domain_discovery_status'),
    
    # Scraping
    path('scraper/initiate/', views.initiate_scraping, name='initiate_scraping'),
    path('scraper/status/<uuid:task_id>/', views.scraping_status, name='scraping_status'),
    
    # Contacts
    path('contacts/', views.ContactListCreateView.as_view(), name='contact_list_create'),
    path('contacts/<int:pk>/', views.ContactDetailView.as_view(), name='contact_detail'),
    path('contacts/bulk-delete/', views.bulk_delete_contacts, name='bulk_delete_contacts'),
    path('contacts/upload-csv/', views.upload_contacts_csv, name='upload_contacts_csv'),
    
    # Email Campaigns
    path('mailer/campaigns/', views.EmailCampaignListCreateView.as_view(), name='campaign_list_create'),
    path('mailer/campaigns/<uuid:pk>/', views.EmailCampaignDetailView.as_view(), name='campaign_detail'),
    path('mailer/campaigns/<uuid:campaign_id>/send/', views.send_campaign, name='send_campaign'),
    path('mailer/campaigns/<uuid:campaign_id>/status/<uuid:sending_task_id>/', views.campaign_sending_status, name='campaign_sending_status'),
    
    # SMTP Configuration
    path('smtp-config/', views.SMTPConfigurationView.as_view(), name='smtp_config'),
    
    # Tracking
    path('tracking/<uuid:campaign_id>/summary/', views.campaign_tracking_summary, name='campaign_tracking_summary'),
    path('tracking/<uuid:campaign_id>/opens/', views.campaign_tracking_opens, name='campaign_tracking_opens'),
    path('tracking/<uuid:campaign_id>/clicks/', views.campaign_tracking_clicks, name='campaign_tracking_clicks'),
    path('tracking/<uuid:campaign_id>/skipped/', views.campaign_tracking_skipped, name='campaign_tracking_skipped'),
    
    # Email tracking (public endpoints)
    path('track/open/<uuid:campaign_id>/<int:contact_id>/', views.email_open_tracking, name='email_open_tracking'),
    path('track/click/<uuid:campaign_id>/<int:contact_id>/', views.email_click_tracking, name='email_click_tracking'),
]

