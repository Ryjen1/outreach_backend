from rest_framework import serializers
from django.contrib.auth.models import User
import os
from .models import (
    DomainDiscoveryTask, ScrapingTask, Contact, EmailCampaign, 
    EmailCampaignContact, EmailSendingTask, EmailTrackingEvent, SMTPConfiguration
)


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password', 'password_confirm', 'first_name', 'last_name')

    def validate(self, data):
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError("Passwords don't match")
        return data

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        user = User.objects.create_user(**validated_data)
        return user


class DomainDiscoveryTaskSerializer(serializers.ModelSerializer):
    discovered_urls = serializers.SerializerMethodField()

    class Meta:
        model = DomainDiscoveryTask
        fields = '__all__'
        read_only_fields = (
            'id', 'user', 'status', 'discovered_urls_count',
            'output_file_path', 'created_at', 'updated_at', 'error_message'
        )

    def get_discovered_urls(self, obj):
        if obj.output_file_path and os.path.exists(obj.output_file_path):
            try:
                with open(obj.output_file_path, 'r') as f:
                    return f.read().splitlines()
            except Exception:
                return []
        return []
class ScrapingTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScrapingTask
        fields = '__all__'
        read_only_fields = ('id', 'user', 'status', 'total_urls', 'processed_urls', 'successful_urls', 'failed_urls', 'output_csv_path', 'created_at', 'updated_at', 'error_message')


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = '__all__'
        read_only_fields = ('user', 'created_at')


class EmailCampaignSerializer(serializers.ModelSerializer):
    contact_count = serializers.SerializerMethodField()

    class Meta:
        model = EmailCampaign
        fields = '__all__'
        read_only_fields = ('id', 'user', 'status', 'created_at', 'updated_at')

    def get_contact_count(self, obj):
        return EmailCampaignContact.objects.filter(campaign=obj).count()


class EmailCampaignContactSerializer(serializers.ModelSerializer):
    contact_details = ContactSerializer(source='contact', read_only=True)

    class Meta:
        model = EmailCampaignContact
        fields = '__all__'


class EmailSendingTaskSerializer(serializers.ModelSerializer):
    campaign_name = serializers.CharField(source='campaign.name', read_only=True)

    class Meta:
        model = EmailSendingTask
        fields = '__all__'
        read_only_fields = ('id', 'status', 'total_recipients', 'sent_count', 'skipped_count', 'failed_count', 'created_at', 'updated_at', 'error_message')


class EmailTrackingEventSerializer(serializers.ModelSerializer):
    contact_email = serializers.CharField(source='contact.email', read_only=True)
    campaign_name = serializers.CharField(source='campaign.name', read_only=True)

    class Meta:
        model = EmailTrackingEvent
        fields = '__all__'


class SMTPConfigurationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = SMTPConfiguration
        fields = '__all__'
        read_only_fields = ('user', 'created_at', 'updated_at')

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Don't return the password in responses
        data.pop('password', None)
        return data


class CampaignCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    subject = serializers.CharField(max_length=255)
    template_content = serializers.CharField()
    contact_ids = serializers.ListField(child=serializers.IntegerField())

    def validate_contact_ids(self, value):
        if not value:
            raise serializers.ValidationError("At least one contact must be selected")
        return value


class BulkContactDeleteSerializer(serializers.Serializer):
    contact_ids = serializers.ListField(child=serializers.IntegerField())

    def validate_contact_ids(self, value):
        if not value:
            raise serializers.ValidationError("At least one contact ID must be provided")
        return value

