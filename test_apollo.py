"""Quick test: verify Apollo API key works and search returns results.

Run with:
  DB_ENGINE=sqlite .venv/bin/python test_apollo.py
"""
import os
os.environ.setdefault('DB_ENGINE', 'sqlite')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')

import django
django.setup()

from api.apollo import ApolloClient, ApolloError

print('=' * 60)
print('Apollo API Connection Test')
print('=' * 60)

try:
    client = ApolloClient()
    print('[1/3] Apollo client initialized with API key from .env')
except ApolloError as e:
    print(f'[1/3] FAILED: {e}')
    raise SystemExit(1)

print()
print('[2/3] Searching Apollo for "barbershop" (5 results, owners/founders/C-suite)...')
try:
    result = client.search_people(
        keyword='barbershop',
        seniorities=['owner', 'founder', 'c_suite'],
        page=1,
        per_page=5,
    )
    people = result['people']
    total = result['total_entries']
    print(f'      Total decision-makers in Apollo matching "barbershop": {total:,}')
    print(f'      Returned {len(people)} people:')
    for i, p in enumerate(people, 1):
        name = f"{p.get('first_name', '')} {p.get('last_name_obfuscated', '')}".strip()
        title = p.get('title', 'N/A')
        org = (p.get('organization') or {}).get('name', 'N/A')
        has_email = 'email' if p.get('has_email') else 'no email'
        print(f'        {i}. {name} — {title} at {org} ({has_email})')
except ApolloError as e:
    print(f'[2/3] FAILED: {e}')
    if e.status_code:
        print(f'      HTTP status: {e.status_code}')
    if e.response_data:
        print(f'      Response: {e.response_data}')
    raise SystemExit(1)

print()
print('[3/3] Testing enrichment on first person (costs 1 Apollo credit)...')
if people:
    first_id = people[0].get('id')
    try:
        enrich_result = client.bulk_enrich([first_id])
        matches = enrich_result['matches']
        credits = enrich_result['credits_consumed']
        if matches:
            m = matches[0]
            print(f'      Credits consumed: {credits}')
            print(f'      Full name: {m.get("name", "N/A")}')
            print(f'      Email: {m.get("email", "N/A")}')
            print(f'      Email status: {m.get("email_status", "N/A")}')
            print(f'      LinkedIn: {m.get("linkedin_url", "N/A")}')
            print(f'      Title: {m.get("title", "N/A")}')
            print(f'      City: {m.get("city", "N/A")}, {m.get("country", "N/A")}')
            org = m.get('organization') or {}
            print(f'      Company: {org.get("name", "N/A")}')
            print(f'      Industry: {org.get("industry", "N/A")}')
            print(f'      Employees: {org.get("estimated_num_employees", "N/A")}')
            history = m.get('employment_history') or []
            print(f'      Career history entries: {len(history)}')
            print()
            print('SUCCESS: Apollo API is working!')
        else:
            print('      No match returned (person may not be enrichable)')
    except ApolloError as e:
        print(f'[3/3] FAILED: {e}')
        if e.status_code:
            print(f'      HTTP status: {e.status_code}')
        if e.response_data:
            print(f'      Response: {e.response_data}')
        print()
        print('Search works but enrichment failed. This may be because:')
        print('  - Your Apollo plan does not include bulk_match endpoint')
        print('  - You are out of Apollo credits')
        print('  - The person ID could not be enriched')
else:
    print('      No people to enrich (search returned 0 results)')
