from rest_framework import generics, status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.pagination import PageNumberPagination
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from django.db.models import Q, Count
from django.http import HttpResponse
from django.utils import timezone
import logging

import uuid
import csv
import io


from .tasks import domain_discovery_task, bulk_scraping_task, email_sending_task

from .models import (
    DomainDiscoveryTask, ScrapingTask, Contact, EmailCampaign, 
    EmailCampaignContact, EmailSendingTask, EmailTrackingEvent, SMTPConfiguration
)
from .serializers import (
    UserRegistrationSerializer, DomainDiscoveryTaskSerializer, ScrapingTaskSerializer,
    ContactSerializer, EmailCampaignSerializer, EmailCampaignContactSerializer,
    EmailSendingTaskSerializer, EmailTrackingEventSerializer, SMTPConfigurationSerializer,
    CampaignCreateSerializer, BulkContactDeleteSerializer
)

logger = logging.getLogger(__name__)


class CustomAuthToken(ObtainAuthToken):
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data,
                                           context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        token, created = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'user_id': user.pk,
            'username': user.username,
            'email': user.email
        })


class UserRegistrationView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, created = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'user_id': user.pk,
            'username': user.username,
            'email': user.email
        }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def logout_view(request):
    try:
        request.user.auth_token.delete()
        return Response({'message': 'Successfully logged out'}, status=status.HTTP_200_OK)
    except:
        return Response({'error': 'Error logging out'}, status=status.HTTP_400_BAD_REQUEST)


# Domain Discovery Views
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def initiate_domain_discovery(request):
    industry_or_seed_domain = request.data.get('industry_or_seed_domain')
    if not industry_or_seed_domain:
        return Response({'error': 'industry_or_seed_domain is required'}, status=status.HTTP_400_BAD_REQUEST)

    task = DomainDiscoveryTask.objects.create(
        user=request.user,
        industry_or_seed_domain=industry_or_seed_domain
    )

    # Start the Celery task
    domain_discovery_task.delay(str(task.id), industry_or_seed_domain)

    serializer = DomainDiscoveryTaskSerializer(task)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def domain_discovery_status(request, task_id):
    task = get_object_or_404(DomainDiscoveryTask, id=task_id, user=request.user)
    serializer = DomainDiscoveryTaskSerializer(task)
    return Response(serializer.data)


# Scraping Views
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def initiate_scraping(request):
    discovery_task_id = request.data.get('discovery_task_id')
    urls_list = request.data.get('urls_list')

    if not discovery_task_id and not urls_list:
        return Response({'error': 'Either discovery_task_id or urls_list is required'}, status=status.HTTP_400_BAD_REQUEST)

    related_discovery_task = None
    urls_file_path = None

    if discovery_task_id:
        related_discovery_task = get_object_or_404(DomainDiscoveryTask, id=discovery_task_id, user=request.user)
        if related_discovery_task.status != 'completed':
            return Response({'error': 'Discovery task must be completed first'}, status=status.HTTP_400_BAD_REQUEST)
        urls_file_path = related_discovery_task.output_file_path

    scraping_task = ScrapingTask.objects.create(
        user=request.user,
        related_domain_discovery_task=related_discovery_task
    )

    # Start the Celery task
    bulk_scraping_task.delay(str(scraping_task.id), urls_file_path, urls_list)

    serializer = ScrapingTaskSerializer(scraping_task)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def scraping_status(request, task_id):
    task = get_object_or_404(ScrapingTask, id=task_id, user=request.user)
    serializer = ScrapingTaskSerializer(task)
    return Response(serializer.data)


# Contact Views
class ContactPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 1000


class ContactListCreateView(generics.ListCreateAPIView):
    serializer_class = ContactSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = ContactPagination

    def get_queryset(self):
        queryset = Contact.objects.filter(user=self.request.user).order_by('-created_at')
        
        # Filtering
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(email__icontains=search) |
                Q(city__icontains=search) |
                Q(country__icontains=search)
            )
        
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ContactDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ContactSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Contact.objects.filter(user=self.request.user)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def bulk_delete_contacts(request):
    serializer = BulkContactDeleteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    contact_ids = serializer.validated_data['contact_ids']
    deleted_count = Contact.objects.filter(id__in=contact_ids, user=request.user).delete()[0]
    
    return Response({'deleted_count': deleted_count}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def upload_contacts_csv(request):
    if 'file' not in request.FILES:
        return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)

    csv_file = request.FILES['file']
    if not csv_file.name.endswith('.csv'):
        return Response({'error': 'File must be a CSV'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        decoded_file = csv_file.read().decode('utf-8')
        io_string = io.StringIO(decoded_file)
        reader = csv.DictReader(io_string)
        
        contacts_created = 0
        for row in reader:
            Contact.objects.create(
                user=request.user,
                source_url=row.get('source_url', ''),
                scraped_on=timezone.now(),
                name=row.get('name', ''),
                email=row.get('email', ''),
                phone=row.get('phone', ''),
                city=row.get('city', ''),
                country=row.get('country', ''),
                personalized_info=row.get('personalized_info', ''),
                status='Imported'
            )
            contacts_created += 1

        return Response({'contacts_created': contacts_created}, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({'error': f'Error processing CSV: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)


# Email Campaign Views
class EmailCampaignListCreateView(generics.ListCreateAPIView):
    serializer_class = EmailCampaignSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return EmailCampaign.objects.filter(user=self.request.user).order_by('-created_at')

    def create(self, request, *args, **kwargs):
        serializer = CampaignCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Create campaign
        campaign = EmailCampaign.objects.create(
            user=request.user,
            name=serializer.validated_data['name'],
            subject=serializer.validated_data['subject'],
            template_content=serializer.validated_data['template_content']
        )

        # Add contacts to campaign
        contact_ids = serializer.validated_data['contact_ids']
        contacts = Contact.objects.filter(id__in=contact_ids, user=request.user)
        
        for contact in contacts:
            EmailCampaignContact.objects.create(campaign=campaign, contact=contact)

        campaign_serializer = EmailCampaignSerializer(campaign)
        return Response(campaign_serializer.data, status=status.HTTP_201_CREATED)


class EmailCampaignDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = EmailCampaignSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return EmailCampaign.objects.filter(user=self.request.user)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def send_campaign(request, campaign_id):
    campaign = get_object_or_404(EmailCampaign, id=campaign_id, user=request.user)
    
    if campaign.status == 'sending':
        return Response({'error': 'Campaign is already being sent'}, status=status.HTTP_400_BAD_REQUEST)

    # Create sending task
    sending_task = EmailSendingTask.objects.create(campaign=campaign)
    
    # Update campaign status
    campaign.status = 'sending'
    campaign.save()

    # Start the Celery task
    email_sending_task.delay(str(sending_task.id))

    serializer = EmailSendingTaskSerializer(sending_task)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def campaign_sending_status(request, campaign_id, sending_task_id):
    campaign = get_object_or_404(EmailCampaign, id=campaign_id, user=request.user)
    sending_task = get_object_or_404(EmailSendingTask, id=sending_task_id, campaign=campaign)
    
    serializer = EmailSendingTaskSerializer(sending_task)
    return Response(serializer.data)


# SMTP Configuration Views
class SMTPConfigurationView(generics.RetrieveUpdateAPIView):
    serializer_class = SMTPConfigurationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        config, created = SMTPConfiguration.objects.get_or_create(user=self.request.user)
        return config

    def perform_update(self, serializer):
        serializer.save(user=self.request.user)


# Tracking Views
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def campaign_tracking_summary(request, campaign_id):
    campaign = get_object_or_404(EmailCampaign, id=campaign_id, user=request.user)
    
    # Get campaign contacts count
    total_recipients = EmailCampaignContact.objects.filter(campaign=campaign).count()
    
    # Get tracking events
    opens = EmailTrackingEvent.objects.filter(campaign=campaign, event_type='open').count()
    clicks = EmailTrackingEvent.objects.filter(campaign=campaign, event_type='click').count()
    
    # Calculate rates
    open_rate = (opens / total_recipients * 100) if total_recipients > 0 else 0
    click_rate = (clicks / total_recipients * 100) if total_recipients > 0 else 0
    
    return Response({
        'campaign_id': campaign_id,
        'campaign_name': campaign.name,
        'total_recipients': total_recipients,
        'opens': opens,
        'clicks': clicks,
        'open_rate': round(open_rate, 2),
        'click_rate': round(click_rate, 2)
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def campaign_tracking_opens(request, campaign_id):
    campaign = get_object_or_404(EmailCampaign, id=campaign_id, user=request.user)
    opens = EmailTrackingEvent.objects.filter(campaign=campaign, event_type='open').order_by('-timestamp')
    serializer = EmailTrackingEventSerializer(opens, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def campaign_tracking_clicks(request, campaign_id):
    campaign = get_object_or_404(EmailCampaign, id=campaign_id, user=request.user)
    clicks = EmailTrackingEvent.objects.filter(campaign=campaign, event_type='click').order_by('-timestamp')
    serializer = EmailTrackingEventSerializer(clicks, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def campaign_tracking_skipped(request, campaign_id):
    campaign = get_object_or_404(EmailCampaign, id=campaign_id, user=request.user)
    
    # Get sending tasks for this campaign
    sending_tasks = EmailSendingTask.objects.filter(campaign=campaign)
    
    skipped_data = []
    for task in sending_tasks:
        skipped_data.append({
            'sending_task_id': task.id,
            'skipped_count': task.skipped_count,
            'failed_count': task.failed_count,
            'error_message': task.error_message,
            'timestamp': task.updated_at
        })
    
    return Response(skipped_data)


# Email tracking pixel and link redirect views
@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def email_open_tracking(request, campaign_id, contact_id):
    """Tracking pixel for email opens"""
    try:
        campaign = EmailCampaign.objects.get(id=campaign_id)
        contact = Contact.objects.get(id=contact_id)
        
        # Record the open event
        EmailTrackingEvent.objects.create(
            campaign=campaign,
            contact=contact,
            event_type='open',
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )
    except:
        pass  # Silently fail for tracking
    
    # Return a 1x1 transparent pixel
    pixel_data = b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00\x21\xF9\x04\x01\x00\x00\x00\x00\x2C\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x04\x01\x00\x3B'
    response = HttpResponse(pixel_data, content_type='image/gif')
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def email_click_tracking(request, campaign_id, contact_id):
    """Link click tracking and redirect"""
    original_url = request.GET.get('url')
    
    try:
        campaign = EmailCampaign.objects.get(id=campaign_id)
        contact = Contact.objects.get(id=contact_id)
        
        # Record the click event
        EmailTrackingEvent.objects.create(
            campaign=campaign,
            contact=contact,
            event_type='click',
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            link_clicked_url=original_url
        )
    except:
        pass  # Silently fail for tracking
    
    # Redirect to the original URL
    if original_url:
        return HttpResponse(f'<script>window.location.href="{original_url}";</script>')
    else:
        return HttpResponse('Invalid link')
