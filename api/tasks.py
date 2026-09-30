import json
import logging
import os
import tempfile
import time

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .scraper import WebsiteScraper
from .models import (
    DomainDiscoveryTask, ScrapingTask, Contact,
    EmailSendingTask, EmailCampaign, EmailCampaignContact,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain Discovery → Apify Google Maps Scraper
# (pay-as-you-go, ~$1.50 / 1k places — replaces Yelp/Overpass)
# ---------------------------------------------------------------------------
@shared_task(bind=True, name='api.tasks.domain_discovery_task')
def domain_discovery_task(self, task_id, keyword, location=None, max_results=1000):
    """Search Google Maps (via Apify) for businesses matching *keyword* in
    *location*.

    Stores the results as a JSONL temp file so the follow-up scraping task
    can scrape each business's website for contact info.
    """
    task = None
    try:
        task = DomainDiscoveryTask.objects.get(id=task_id)
        task.status = 'running'
        task.save(update_fields=['status', 'updated_at'])

        logger.info('Apify discovery: %s in %s', keyword, location)

        from .apify import ApifyClient, ApifyError

        apify_token = getattr(settings, 'APIFY_API_TOKEN', '')
        if not apify_token:
            raise ApifyError(
                'APIFY_API_TOKEN is not configured. Get a token from '
                'https://console.apify.com/account/integrations'
            )

        client = ApifyClient(api_token=apify_token)

        def on_progress(run_data, elapsed):
            stats = run_data.get('stats', {}) or {}
            items = stats.get('datasetItemsCount', 0)
            task.discovered_urls_count = items
            task.save(update_fields=['discovered_urls_count', 'updated_at'])

        result = client.search_businesses(
            keyword=keyword,
            location=location or 'New York',
            max_results=max_results,
            progress_callback=on_progress,
        )
        businesses = result['businesses']

        # Persist business data as JSONL (same shape bulk_scraping_task expects)
        temp_dir = tempfile.gettempdir()
        output_file = os.path.join(temp_dir, f'apify_businesses_{task_id}.jsonl')
        with open(output_file, 'w') as f:
            for biz in businesses:
                f.write(json.dumps(biz) + '\n')

        task.discovered_urls_count = len(businesses)
        task.output_file_path = output_file
        task.status = 'completed'
        task.save(update_fields=[
            'discovered_urls_count', 'output_file_path', 'status', 'updated_at',
        ])

        logger.info('Discovery complete: %d businesses found', len(businesses))
        return {
            'status': 'completed',
            'businesses_found': len(businesses),
            'raw_count': result.get('raw_count', len(businesses)),
            'apify_run_id': result.get('run_id'),
        }

    except Exception as e:
        logger.exception('Domain discovery task failed.')
        if task:
            task.status = 'failed'
            task.error_message = str(e)
            task.save(update_fields=['status', 'error_message', 'updated_at'])
        raise


# ---------------------------------------------------------------------------
# Bulk Scraping → Scrape each business's website for contact info
# ---------------------------------------------------------------------------
@shared_task(bind=True, name='api.tasks.bulk_scraping_task')
def bulk_scraping_task(self, task_id, urls_file_path=None, urls_list=None, max_contacts=100):
    """Scrape contact information from the websites of businesses found
    in the discovery step.

    For each business with a website, fetches the homepage + common contact
    pages and extracts emails, phone numbers, LinkedIn/social URLs, and
    any person names found on team/about pages.
    """
    task = None
    try:
        task = ScrapingTask.objects.get(id=task_id)
        task.status = 'running'
        task.save(update_fields=['status', 'updated_at'])

        # Load businesses from the discovery JSONL file, or accept raw URLs
        businesses = []
        if urls_file_path and os.path.exists(urls_file_path):
            with open(urls_file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        businesses.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        elif urls_list:
            # urls_list can be either a list of URL strings, or a list of
            # business dicts (from discovery). Normalize to business dicts.
            for item in urls_list:
                if isinstance(item, dict):
                    businesses.append(item)
                elif isinstance(item, str):
                    businesses.append({
                        'name': '',
                        'website': item,
                        'phone': '',
                        'email': '',
                        'city': '',
                        'country': '',
                        'category': '',
                    })
        else:
            raise ValueError('No businesses or URLs provided for scraping.')

        # Cap at max_contacts
        if max_contacts and len(businesses) > max_contacts:
            logger.info('Capping scraping from %d to %d businesses', len(businesses), max_contacts)
            businesses = businesses[:max_contacts]

        task.total_urls = len(businesses)
        task.save(update_fields=['total_urls', 'updated_at'])

        scraper = WebsiteScraper(timeout=15, max_pages=4)
        processed = 0
        successful = 0
        failed = 0

        for biz in businesses:
            website = biz.get('website', '')
            biz_name = biz.get('name', 'Unknown')
            biz_email = biz.get('email', '')
            biz_emails = biz.get('emails', [])
            biz_phone = biz.get('phone', '')
            biz_instagram = biz.get('instagram', '')
            biz_facebook = biz.get('facebook', '')
            biz_linkedin = biz.get('linkedin', '')

            try:
                # If Apify's scrapeContacts already found an email, skip the
                # website scrape — we have what we need for email marketing.
                if biz_email:
                    emails = biz_emails if biz_emails else [biz_email]
                    phones = [biz_phone] if biz_phone else []
                    linkedin = biz_linkedin
                    facebook = biz_facebook
                    names = []
                    scraped_name = ''
                    logger.info('Using Apify-provided email for %s: %s',
                                biz_name, biz_email)
                else:
                    # No email from Apify — scrape the website if there is one
                    result = scraper.scrape(website, business_name=biz_name) \
                        if website else {}

                    emails = result.get('emails', [])
                    phones = result.get('phones', [])
                    linkedin = result.get('linkedin_url', '') or biz_linkedin
                    facebook = result.get('facebook_url', '') or biz_facebook
                    names = result.get('names', [])
                    scraped_name = result.get('business_name', '')

                # Build personalized info from scraped/enriched data
                personalized_parts = []
                if linkedin:
                    personalized_parts.append(f'LinkedIn: {linkedin}')
                if facebook:
                    personalized_parts.append(f'Facebook: {facebook}')
                if biz_instagram:
                    personalized_parts.append(f'Instagram: {biz_instagram}')
                if names:
                    personalized_parts.append(f'Possible contacts: {", ".join(names[:3])}')
                personalized_info = ' | '.join(personalized_parts)

                # Determine the primary name/email/phone
                # Priority: discovery name (from Google Maps) > scraped name
                # The discovery name is from Google Maps business listing,
                # which is the actual business name. The scraped name from
                # <title> is often SEO keywords, so only use it as fallback
                # (e.g. for manual URL entry where there's no discovery name).
                name = biz_name or scraped_name
                email = emails[0] if emails else biz_email
                phone = phones[0] if phones else biz_phone

                # For email marketing: only import contacts that have an email.
                # Contacts with just a phone or social link but no email are
                # useless for email campaigns.
                if not email:
                    failed += 1
                    processed += 1
                    task.processed_urls = processed
                    task.failed_urls = failed
                    task.save(update_fields=['processed_urls', 'failed_urls', 'updated_at'])
                    continue

                # Skip duplicates (same email or same business name for this user)
                if email and Contact.objects.filter(
                    user=task.user, email=email
                ).exists():
                    logger.info('Skipping duplicate: %s', email)
                    processed += 1
                    task.processed_urls = processed
                    task.save(update_fields=['processed_urls', 'updated_at'])
                    continue

                Contact.objects.create(
                    user=task.user,
                    scraping_task=task,
                    source_url=website or 'https://openstreetmap.org',
                    scraped_on=timezone.now(),
                    name=name or biz_name,
                    email=email,
                    phone=phone,
                    city=biz.get('city', ''),
                    country=biz.get('country', ''),
                    personalized_info=personalized_info,
                    status='Scraped',
                    company_name=biz_name,
                    company_website=website,
                    linkedin_url=linkedin,
                    company_linkedin_url=linkedin,  # company LinkedIn (not personal)
                    company_industry=biz.get('category', ''),
                    career_history=[],
                )
                successful += 1

            except Exception as e:
                logger.error('Failed to scrape %s: %s', biz_name, e)
                failed += 1

            processed += 1
            task.processed_urls = processed
            task.successful_urls = successful
            task.failed_urls = failed
            task.save(update_fields=[
                'processed_urls', 'successful_urls', 'failed_urls', 'updated_at',
            ])

            # Small delay to be polite
            time.sleep(0.3)

        task.status = 'completed'
        task.save(update_fields=['status', 'updated_at'])

        logger.info('Scraping complete: %d processed, %d successful, %d failed',
                    processed, successful, failed)
        return {
            'status': 'completed',
            'processed': processed,
            'successful': successful,
            'failed': failed,
        }

    except Exception as e:
        logger.exception('Bulk scraping task failed.')
        if task:
            task.status = 'failed'
            task.error_message = str(e)
            task.save(update_fields=['status', 'error_message', 'updated_at'])
        raise


# ---------------------------------------------------------------------------
# Email Sending (stub — unchanged)
# ---------------------------------------------------------------------------
@shared_task(bind=True, name='api.tasks.email_sending_task')
def email_sending_task(self, sending_task_id):
    """Send an email campaign to all associated contacts via SMTP."""
    sending_task = None
    try:
        sending_task = EmailSendingTask.objects.get(id=sending_task_id)
        campaign = sending_task.campaign

        sending_task.status = 'running'
        sending_task.save(update_fields=['status', 'updated_at'])

        logger.info('[%s] Sending campaign "%s"', self.request.id, campaign.name)

        campaign_contacts = EmailCampaignContact.objects.filter(campaign=campaign)
        sending_task.total_recipients = campaign_contacts.count()
        sending_task.save(update_fields=['total_recipients', 'updated_at'])

        sent = 0
        skipped = 0
        failed = 0

        for cc in campaign_contacts:
            contact = cc.contact
            if not contact.email:
                skipped += 1
                continue
            try:
                # TODO: implement actual SMTP send via django.core.mail
                time.sleep(0.1)
                sent += 1
            except Exception:
                failed += 1

        sending_task.sent_count = sent
        sending_task.skipped_count = skipped
        sending_task.failed_count = failed
        sending_task.status = 'completed'
        campaign.status = 'completed'
        campaign.save(update_fields=['status', 'updated_at'])
        sending_task.save(update_fields=[
            'sent_count', 'skipped_count', 'failed_count', 'status', 'updated_at',
        ])

        return {'status': 'completed', 'sent': sent, 'skipped': skipped, 'failed': failed}

    except Exception as e:
        logger.exception('Email sending task failed.')
        if sending_task:
            sending_task.status = 'failed'
            sending_task.error_message = str(e)
            sending_task.save(update_fields=['status', 'error_message', 'updated_at'])
        raise
