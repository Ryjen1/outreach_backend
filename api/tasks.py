import logging
import os
import tempfile
from datetime import datetime
import time

#import pandas as pd
from celery import shared_task
from django.utils import timezone

from .models import (
    DomainDiscoveryTask, ScrapingTask, Contact,
    EmailSendingTask, EmailCampaign, EmailCampaignContact, SMTPConfiguration
)
from .scraper import WebScraper

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="api.tasks.domain_discovery_task")
def domain_discovery_task(self, task_id, industry_or_seed_domain):
    task = None
    try:
        task = DomainDiscoveryTask.objects.get(id=task_id)

        task.status = 'running'
        task.save(update_fields=['status', 'updated_at'])

        logger.info(f"[{self.request.id}] Starting domain discovery for: {industry_or_seed_domain}")

        if industry_or_seed_domain.startswith('http'):
            base_domain = industry_or_seed_domain.rstrip('/')
            discovered_urls = [base_domain]
            for path in ['/about', '/contact', '/team', '/company']:
                discovered_urls.append(f"{base_domain}{path}")
        else:
            discovered_urls = [
                f"https://example-{industry_or_seed_domain.replace(' ', '-').lower()}-{i}.com"
                for i in range(1, 101)
            ]

        temp_dir = tempfile.gettempdir()
        output_file = os.path.join(temp_dir, f'discovered_urls_{task_id}.txt')
        with open(output_file, 'w') as f:
            f.write('\n'.join(discovered_urls))

        task.discovered_urls_count = len(discovered_urls)
        task.output_file_path = output_file
        task.status = 'completed'
        task.save(update_fields=['discovered_urls_count', 'output_file_path', 'status', 'updated_at'])

        return {
            'status': 'completed',
            'urls_count': len(discovered_urls),
            'file_path': output_file
        }

    except Exception as e:
        logger.exception("Domain discovery task failed.")
        if task:
            task.status = 'failed'
            task.error_message = str(e)
            task.save(update_fields=['status', 'error_message', 'updated_at'])
        raise


@shared_task(bind=True, name="api.tasks.bulk_scraping_task")
def bulk_scraping_task(self, task_id, urls_file_path=None, urls_list=None):
    task = None
    try:
        task = ScrapingTask.objects.get(id=task_id)
        task.status = 'running'
        task.save(update_fields=['status', 'updated_at'])

        # Get list of URLs
        if urls_file_path and os.path.exists(urls_file_path):
            with open(urls_file_path, 'r') as f:
                urls_to_scrape = [line.strip() for line in f if line.strip()]
        elif urls_list:
            urls_to_scrape = urls_list
        else:
            raise ValueError("No URLs provided for scraping.")

        task.total_urls = len(urls_to_scrape)
        task.save(update_fields=['total_urls', 'updated_at'])

        scraper = WebScraper(rate_limit=0.5, max_workers=10)
        scraped_results = scraper.run(urls_to_scrape)

        contacts_created = 0
        for result in scraped_results:
            contact = Contact.objects.create(
                user=task.user,
                scraping_task=task,
                source_url=result.get('source_url'),
                scraped_on=datetime.strptime(result.get('scraped_on'), '%Y-%m-%d %H:%M:%S'),
                name=result.get('name'),
                email=result.get('email'),
                phone=result.get('phone'),
                city=result.get('city'),
                country=result.get('country'),
                personalized_info=result.get('personalized_info'),
                status=result.get('status')
            )
            if result.get('status') == 'Success':
                contacts_created += 1

        task.processed_urls = len(scraped_results)
        task.successful_urls = contacts_created
        task.failed_urls = task.processed_urls - contacts_created
        task.status = 'completed'

        temp_dir = tempfile.gettempdir()
        output_csv = os.path.join(temp_dir, f'scraped_data_{task_id}.csv')
        pd.DataFrame(scraped_results).to_csv(output_csv, index=False)

        task.output_csv_path = output_csv
        task.save(update_fields=[
            'processed_urls', 'successful_urls', 'failed_urls',
            'status', 'output_csv_path', 'updated_at'
        ])

        return {
            'status': 'completed',
            'processed_urls': task.processed_urls,
            'successful_urls': task.successful_urls,
            'failed_urls': task.failed_urls
        }

    except Exception as e:
        logger.exception("Bulk scraping task failed.")
        if task:
            task.status = 'failed'
            task.error_message = str(e)
            task.save(update_fields=['status', 'error_message', 'updated_at'])
        raise


@shared_task(bind=True, name="api.tasks.email_sending_task")
def email_sending_task(self, campaign_id):
    try:
        campaign = EmailCampaign.objects.get(id=campaign_id)
        logger.info(f"[{self.request.id}] Sending campaign {campaign.subject} to contacts...")

        time.sleep(5)  # simulate delay

        campaign.status = 'sent'
        campaign.save(update_fields=['status', 'updated_at'])
        return {'status': 'sent', 'campaign_id': campaign_id}

    except Exception as e:
        logger.exception("Email sending task failed.")
        raise
