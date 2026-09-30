"""Apify client for the Google Maps Scraper actor.

Wraps the ``compass/crawler-google-places`` actor via the Apify REST API v2.
Discovers local businesses (name, website, phone, address, category) for a
given keyword + location — replaces the previous Yelp/Overpass discovery layer.

Pricing: ~$1.50 / 1,000 scraped places (pay-as-you-go, no monthly commitment).
Get a token: https://console.apify.com/account/integrations
"""

import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

APIFY_API_BASE = 'https://api.apify.com/v2'
GOOGLE_MAPS_SCRAPER_ACTOR_ID = 'compass~crawler-google-places'

# Statuses that indicate a run is done (not still running)
TERMINAL_STATUSES = {'SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'}


class ApifyError(Exception):
    """Raised when the Apify API returns an error or a run fails."""

    def __init__(self, message, status_code=None, response_data=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


class ApifyClient:
    """Client for Apify actors via the REST API v2.

    Currently wraps the Google Maps Scraper actor
    (``compass/crawler-google-places``) for local-business discovery.
    All calls require an API token configured via ``APIFY_API_TOKEN``.
    """

    def __init__(self, api_token=None):
        self.api_token = api_token or getattr(settings, 'APIFY_API_TOKEN', '')
        if not self.api_token:
            raise ApifyError(
                'APIFY_API_TOKEN is not configured. Set it in the .env file. '
                'Get a token from https://console.apify.com/account/integrations'
            )
        self.session = requests.Session()
        self.session.params = {'token': self.api_token}
        self.session.headers.update({'Content-Type': 'application/json'})

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------
    def _request(self, method, path, json_body=None, params=None, timeout=30):
        """HTTP wrapper with basic error handling."""
        url = f'{APIFY_API_BASE}{path}'
        try:
            response = self.session.request(
                method, url, json=json_body, params=params, timeout=timeout,
            )
        except requests.RequestException as exc:
            raise ApifyError(f'Network error calling Apify: {exc}') from exc

        if response.status_code == 401:
            raise ApifyError(
                'Invalid Apify token. Check APIFY_API_TOKEN in .env',
                status_code=401,
            )

        if not (200 <= response.status_code < 300):
            data = {}
            try:
                data = response.json()
            except Exception:
                data = {'raw': response.text}
            raise ApifyError(
                data.get('error', {}).get('message', f'Apify API error {response.status_code}'),
                status_code=response.status_code,
                response_data=data,
            )

        try:
            return response.json()
        except Exception as exc:
            raise ApifyError(f'Could not parse Apify response: {exc}') from exc

    # ------------------------------------------------------------------
    # Actor run lifecycle
    # ------------------------------------------------------------------
    def start_run(self, actor_id, run_input, wait_for_finish_secs=0):
        """Start an actor run.

        Parameters
        ----------
        actor_id : str
            Actor identifier, e.g. ``compass~crawler-google-places``.
        run_input : dict
            JSON input matching the actor's input schema.
        wait_for_finish_secs : int
            If > 0, the API will block up to this many seconds waiting for
            the run to finish before returning.  Useful for short runs.

        Returns
        -------
        dict  with ``id`` (run ID), ``status``, ``defaultDatasetId``, etc.
        """
        path = f'/acts/{actor_id}/runs'
        params = {}
        if wait_for_finish_secs:
            params['waitForFinish'] = wait_for_finish_secs
        data = self._request('POST', path, json_body=run_input, params=params)
        return data.get('data', data)

    def get_run(self, run_id):
        """Get the current status of a run."""
        data = self._request('GET', f'/actor-runs/{run_id}')
        return data.get('data', data)

    def wait_for_run(self, run_id, poll_interval=10, timeout=600,
                     progress_callback=None):
        """Poll a run until it reaches a terminal status.

        Parameters
        ----------
        run_id : str
        poll_interval : int
            Seconds between polls.
        timeout : int
            Maximum seconds to wait before giving up.
        progress_callback : callable | None
            Called with ``(run_data, elapsed_secs)`` after each poll so
            Celery tasks can update the DB row.
        """
        elapsed = 0
        while elapsed < timeout:
            run = self.get_run(run_id)
            status = run.get('status', '')
            stats = run.get('stats', {}) or {}
            finished = status in TERMINAL_STATUSES

            if progress_callback:
                progress_callback(run, elapsed)

            if finished:
                if status != 'SUCCEEDED':
                    raise ApifyError(
                        f'Apify run {run_id} ended with status {status}',
                        response_data=run,
                    )
                return run

            logger.info(
                'Apify run %s: status=%s dataset_items=%s elapsed=%ss',
                run_id, status,
                stats.get('datasetItemsCount', 0), elapsed,
            )
            time.sleep(poll_interval)
            elapsed += poll_interval

        raise ApifyError(
            f'Apify run {run_id} timed out after {timeout}s',
            response_data=self.get_run(run_id) if run_id else None,
        )

    def get_dataset_items(self, dataset_id, limit=None, offset=0):
        """Fetch items from an Apify dataset."""
        params = {'clean': 'true'}
        if limit is not None:
            params['limit'] = limit
        if offset:
            params['offset'] = offset
        data = self._request('GET', f'/datasets/{dataset_id}/items', params=params)
        # dataset items endpoint returns a bare JSON array
        if isinstance(data, list):
            return data
        return data.get('items', data)

    # ------------------------------------------------------------------
    # High-level: Google Maps Scraper
    # ------------------------------------------------------------------
    def search_businesses(self, keyword, location, max_results=100,
                          language='en', country_code=None,
                          skip_closed_places=True, scrape_contacts=True,
                          website_filter='withWebsite',
                          progress_callback=None):
        """Search Google Maps for businesses matching *keyword* in *location*.

        Parameters
        ----------
        keyword : str
            What you'd type in the Google Maps search bar, e.g.
            ``"barbershop"`` or ``"italian restaurant"``.
        location : str
            Free-text location, e.g. ``"Lagos"`` or ``"New York, US"``.
        max_results : int
            Maximum places to scrape per search term.
        language : str
            Results language (e.g. ``"en"``).
        country_code : str | None
            Optional ISO country code (e.g. ``"US"``).
        skip_closed_places : bool
            Skip temporarily/permanently closed businesses.
        scrape_contacts : bool
            Enrich with company emails + social profiles scraped from each
            business's website.  Costs extra but provides emails directly.
        website_filter : str
            Filter by website presence. Options:
            - ``'withWebsite'``: only businesses WITH a website (default —
              needed for email marketing since emails come from websites).
            - ``'withoutWebsite'``: only businesses without a website.
            - ``'allPlaces'``: no filter, return all businesses.
            - ``''`` (empty): no filter.
        progress_callback : callable | None
            Called as ``(run_data, elapsed_secs)`` while polling.

        Returns
        -------
        dict  with ``businesses`` (list of normalized dicts) and
              ``raw_count`` (int — total items returned by Apify).
        """
        run_input = {
            'searchStringsArray': [keyword],
            'locationQuery': location,
            'maxCrawledPlacesPerSearch': max_results,
            'language': language,
            'skipClosedPlaces': skip_closed_places,
            'scrapeContacts': scrape_contacts,
        }
        if website_filter:
            run_input['website'] = website_filter
        if country_code:
            run_input['countryCode'] = country_code

        logger.info(
            'Starting Apify Google Maps Scraper: keyword=%r location=%r max=%d website=%s',
            keyword, location, max_results, website_filter or 'all',
        )

        run = self.start_run(GOOGLE_MAPS_SCRAPER_ACTOR_ID, run_input)
        run_id = run.get('id')
        if not run_id:
            raise ApifyError('Apify did not return a run ID', response_data=run)

        self.wait_for_run(
            run_id,
            poll_interval=10,
            timeout=max(600, max_results * 3),
            progress_callback=progress_callback,
        )

        # Refetch to get the final dataset ID
        run = self.get_run(run_id)
        dataset_id = run.get('defaultDatasetId')
        if not dataset_id:
            raise ApifyError('Apify run has no defaultDatasetId', response_data=run)

        raw_items = self.get_dataset_items(dataset_id, limit=max_results)
        businesses = [self.normalize_business(item) for item in raw_items]
        businesses = [b for b in businesses if b]

        logger.info(
            'Apify discovery complete: %d raw items, %d normalized businesses',
            len(raw_items), len(businesses),
        )

        return {
            'businesses': businesses,
            'raw_count': len(raw_items),
            'run_id': run_id,
            'dataset_id': dataset_id,
        }

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------
    @staticmethod
    def normalize_business(item):
        """Convert a raw Google Maps Scraper output item into a flat dict
        matching the shape expected by ``bulk_scraping_task``.

        When ``scrapeContacts=True`` is passed to ``search_businesses``,
        Apify enriches each place with emails and social profiles scraped
        from the business's website.  Those are extracted here.

        Returns ``None`` if the item has no title (not a real business).
        """
        title = item.get('title', '').strip()
        if not title:
            return None

        location_obj = item.get('location') or {}

        # Extract email(s) — Apify returns a list when scrapeContacts is on
        emails = item.get('emails') or []
        if isinstance(emails, str):
            emails = [emails]
        primary_email = emails[0] if emails else ''

        # Extract social media profiles
        instagrams = item.get('instagrams') or []
        facebooks = item.get('facebooks') or []
        linked_ins = item.get('linkedIns') or []

        return {
            'name': title,
            'website': item.get('website', '') or '',
            'phone': item.get('phone', '') or item.get('phoneUnformatted', '') or '',
            'email': primary_email,
            'emails': emails,
            'city': item.get('city', '') or '',
            'country': item.get('countryCode', '') or '',
            'category': item.get('categoryName', '') or '',
            'address': item.get('address', '') or '',
            'state': item.get('state', '') or '',
            'postal_code': item.get('postalCode', '') or '',
            'latitude': location_obj.get('lat'),
            'longitude': location_obj.get('lng'),
            'rating': item.get('totalScore'),
            'reviews_count': item.get('reviewsCount'),
            'google_maps_url': item.get('url', '') or '',
            'place_id': item.get('placeId', '') or '',
            'categories': item.get('categories', []) or [],
            'instagram': instagrams[0] if instagrams else '',
            'facebook': facebooks[0] if facebooks else '',
            'linkedin': linked_ins[0] if linked_ins else '',
        }
