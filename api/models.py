from django.db import models
from django.contrib.auth.models import User
import uuid


class DomainDiscoveryTask(models.Model):
    """Model to track domain discovery tasks."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    industry_or_seed_domain = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    discovered_urls_count = models.IntegerField(default=0)
    output_file_path = models.CharField(max_length=500, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    error_message = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Discovery Task {self.id} - {self.status}"


class ScrapingTask(models.Model):
    """Model to track scraping tasks."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    related_domain_discovery_task = models.ForeignKey(DomainDiscoveryTask, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    total_urls = models.IntegerField(default=0)
    processed_urls = models.IntegerField(default=0)
    successful_urls = models.IntegerField(default=0)
    failed_urls = models.IntegerField(default=0)
    output_csv_path = models.CharField(max_length=500, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    error_message = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Scraping Task {self.id} - {self.status}"


class Contact(models.Model):
    """Model to store scraped contact information."""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    scraping_task = models.ForeignKey(ScrapingTask, on_delete=models.CASCADE, null=True, blank=True)
    source_url = models.URLField(max_length=2000)
    scraped_on = models.DateTimeField()
    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    city = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    personalized_info = models.TextField(blank=True)
    status = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Contact: {self.name or self.email or 'Unknown'}"


class EmailCampaign(models.Model):
    """Model to store email campaigns."""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sending', 'Sending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    template_content = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Campaign: {self.name}"


class EmailCampaignContact(models.Model):
    """Model to link campaigns with contacts."""
    campaign = models.ForeignKey(EmailCampaign, on_delete=models.CASCADE)
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('campaign', 'contact')


class EmailSendingTask(models.Model):
    """Model to track email sending tasks."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campaign = models.ForeignKey(EmailCampaign, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    total_recipients = models.IntegerField(default=0)
    sent_count = models.IntegerField(default=0)
    skipped_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    error_message = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Sending Task {self.id} for Campaign {self.campaign.name}"


class EmailTrackingEvent(models.Model):
    """Model to track email events (opens, clicks)."""
    EVENT_TYPES = [
        ('open', 'Email Open'),
        ('click', 'Link Click'),
    ]
    
    campaign = models.ForeignKey(EmailCampaign, on_delete=models.CASCADE)
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE)
    event_type = models.CharField(max_length=10, choices=EVENT_TYPES)
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    link_clicked_url = models.URLField(max_length=2000, blank=True, null=True)

    def __str__(self):
        return f"{self.event_type} - {self.contact.email} - {self.campaign.name}"


class SMTPConfiguration(models.Model):
    """Model to store SMTP configuration per user."""
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    smtp_server = models.CharField(max_length=255)
    smtp_port = models.IntegerField()
    username = models.CharField(max_length=255)
    password = models.CharField(max_length=255)  # Should be encrypted in production
    from_name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"SMTP Config for {self.user.username}"

