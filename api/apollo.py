import logging
import time
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

APOLLO_BASE_URL = getattr(settings, 'APOLLO_API_BASE_URL', 'https://api.apollo.io/api/v1')
APOLLO_API_KEY = getattr(settings, 'APOLLO_API_KEY', '')

# Default seniority levels for decision-makers
DEFAULT_SENIORITIES = ['owner', 'founder', 'c_suite']


class ApolloError(Exception):
    """Raised when the Apollo API returns an error."""

    def __init__(self, message, status_code=None, response_data=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


class ApolloClient:
    """Client for the Apollo.io REST API.

    Wraps the People Search (free, 0 credits) and Bulk People Enrichment
    (1-9 credits/person) endpoints.  All calls require an API key configured
    via the ``APOLLO_API_KEY`` setting.
    """

    def __init__(self, api_key=None):
        self.api_key = api_key or APOLLO_API_KEY
        if not self.api_key:
            raise ApolloError(
                'APOLLO_API_KEY is not configured. Set it in the .env file. '
                'Get a key from https://app.apollo.io/#/settings/integrations/api'
            )
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Cache-Control': 'no-cache',
            'x-api-key': self.api_key,
        })

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------
    def _post(self, path, params=None, json_body=None, retry_on_429=True):
        """POST wrapper with automatic retry on rate-limit (429)."""
        url = f'{APOLLO_BASE_URL}{path}'
        for attempt in range(3):
            try:
                response = self.session.post(url, params=params, json=json_body, timeout=30)
            except requests.RequestException as exc:
                raise ApolloError(f'Network error calling Apollo: {exc}') from exc

            if response.status_code == 429 and retry_on_429 and attempt < 2:
                wait = 5 * (attempt + 1)
                logger.warning('Apollo rate-limited (429). Retrying in %ss…', wait)
                time.sleep(wait)
                continue

            if response.status_code == 401:
                raise ApolloError(
                    'Invalid Apollo API key. Check APOLLO_API_KEY in .env',
                    status_code=401,
                )

            if response.status_code == 403:
                data = {}
                try:
                    data = response.json()
                except Exception:
                    pass
                raise ApolloError(
                    data.get('message', 'Apollo API access denied (403). '
                              'The endpoint may require a paid Apollo plan.'),
                    status_code=403,
                    response_data=data,
                )

            if not (200 <= response.status_code < 300):
                data = {}
                try:
                    data = response.json()
                except Exception:
                    data = {'raw': response.text}
                raise ApolloError(
                    data.get('message', f'Apollo API error {response.status_code}'),
                    status_code=response.status_code,
                    response_data=data,
                )

            try:
                return response.json()
            except Exception as exc:
                raise ApolloError(f'Could not parse Apollo response: {exc}') from exc

        raise ApolloError('Apollo API rate-limited after 3 retries', status_code=429)

    # ------------------------------------------------------------------
    # People Search  (0 credits — returns obfuscated names, no email)
    # ------------------------------------------------------------------
    def search_people(self, keyword, seniorities=None, page=1, per_page=100,
                      person_titles=None, organization_locations=None):
        """Search Apollo's people database.

        Parameters
        ----------
        keyword : str
            Free-text keyword, e.g. ``"barbershop"`` or ``"fintech"``.
        seniorities : list[str] | None
            Seniority filters. Defaults to ``["owner", "founder", "c_suite"]``.
        page : int
            1-indexed page number.
        per_page : int
            Results per page (max 100).
        person_titles : list[str] | None
            Optional job-title filter, e.g. ``["CEO", "Founder"]``.

        Returns
        -------
        dict  with ``people`` (list) and ``total_entries`` (int)
        """
        if seniorities is None:
            seniorities = DEFAULT_SENIORITIES

        params = {
            'q_keywords': keyword,
            'page': page,
            'per_page': min(per_page, 100),
        }
        for s in seniorities:
            params.setdefault('person_seniorities[]', [])
            if isinstance(params['person_seniorities[]'], list):
                params['person_seniorities[]'].append(s)
        # Convert list params to repeated query params
        flat_params = self._flatten_params(params)

        if person_titles:
            for t in person_titles:
                flat_params.append(('person_titles[]', t))
        if organization_locations:
            for loc in organization_locations:
                flat_params.append(('organization_locations[]', loc))

        data = self._post('/mixed_people/api_search', params=flat_params)
        people = data.get('people', [])
        total = data.get('total_entries', 0)
        return {'people': people, 'total_entries': total}

    def search_all_people(self, keyword, max_results=1000, seniorities=None,
                          person_titles=None, organization_locations=None,
                          progress_callback=None):
        """Paginate through people search up to ``max_results``.

        ``progress_callback`` is called with ``(page, collected, total)`` after
        each page so Celery tasks can update the DB row.
        """
        collected = []
        total = 0
        page = 1
        while len(collected) < max_results:
            result = self.search_people(
                keyword=keyword,
                seniorities=seniorities,
                page=page,
                per_page=100,
                person_titles=person_titles,
                organization_locations=organization_locations,
            )
            people = result['people']
            total = result['total_entries']
            if not people:
                break
            collected.extend(people)
            if progress_callback:
                progress_callback(page, len(collected), total)
            if len(people) < 100:
                break  # last page
            page += 1
            if page > 500:  # API hard limit
                break
            time.sleep(0.3)  # be nice to the API
        return {'people': collected[:max_results], 'total_entries': total}

    # ------------------------------------------------------------------
    # Bulk People Enrichment  (1-9 credits/person — returns email, LinkedIn, career history)
    # ------------------------------------------------------------------
    def bulk_enrich(self, person_ids, reveal_personal_emails=True):
        """Enrich up to 10 people by their Apollo IDs.

        Returns the ``matches`` list from the API response.  Each match
        contains full name, email, LinkedIn URL, phone, city, country,
        employment history, and organization details.
        """
        if len(person_ids) > 10:
            raise ValueError('bulk_enrich accepts at most 10 person IDs per call')

        details = [{'id': pid} for pid in person_ids]
        params = {
            'reveal_personal_emails': reveal_personal_emails,
        }
        body = {'details': details}
        data = self._post('/people/bulk_match', params=params, json_body=body)
        matches = data.get('matches', [])
        credits_consumed = data.get('credits_consumed', 0)
        return {'matches': matches, 'credits_consumed': credits_consumed}

    def enrich_in_batches(self, person_ids, batch_size=10, progress_callback=None):
        """Enrich a list of person IDs in batches of ``batch_size``.

        Returns a flat list of enriched match objects.
        """
        enriched = []
        for i in range(0, len(person_ids), batch_size):
            batch = person_ids[i:i + batch_size]
            result = self.bulk_enrich(batch)
            matches = result['matches']
            credits = result['credits_consumed']
            enriched.extend(matches)
            if progress_callback:
                progress_callback(i // batch_size + 1, len(enriched), credits)
            if i + batch_size < len(person_ids):
                time.sleep(0.5)
        return enriched

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------
    @staticmethod
    def _flatten_params(params):
        """Convert a dict with list values into a list of (key, value) tuples
        suitable for ``requests`` params."""
        flat = []
        for key, val in params.items():
            if isinstance(val, list):
                for v in val:
                    flat.append((key, v))
            else:
                flat.append((key, val))
        return flat

    @staticmethod
    def normalize_person(match):
        """Convert an enriched Apollo match into a flat dict suitable for the
        Contact model."""
        org = match.get('organization') or {}

        employment_history = match.get('employment_history') or []
        career_summary = []
        for job in employment_history[:5]:
            title = job.get('title', '')
            org_name = job.get('organization_name', '')
            current = ' (Current)' if job.get('current') else ''
            start = job.get('start_date', '')
            end = job.get('end_date', '') or 'present'
            career_summary.append(f'{title} at {org_name}{current} [{start} – {end}]')

        personalized = ' | '.join(career_summary) if career_summary else ''

        return {
            'apollo_person_id': match.get('id', ''),
            'name': match.get('name', '') or f"{match.get('first_name', '')} {match.get('last_name', '')}".strip(),
            'email': match.get('email', '') or '',
            'phone': match.get('organization', {}).get('phone', '') or '',
            'city': match.get('city', '') or '',
            'country': match.get('country', '') or '',
            'job_title': match.get('title', '') or '',
            'company_name': org.get('name', '') or '',
            'company_website': org.get('website_url', '') or '',
            'linkedin_url': match.get('linkedin_url', '') or '',
            'company_linkedin_url': org.get('linkedin_url', '') or '',
            'company_industry': org.get('industry', '') or '',
            'company_employee_count': org.get('estimated_num_employees'),
            'career_history': employment_history,
            'personalized_info': personalized,
            'email_status': match.get('email_status', '') or '',
            'source_url': org.get('website_url', '') or 'https://apollo.io',
        }
