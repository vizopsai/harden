"""
Celery tasks for background processing
"""
from celery import Celery
import requests
import time

# Configure Celery
# TODO: use environment variables for broker URL
celery = Celery('tasks', broker='redis://redis:6379/0')

celery.conf.update(
    result_backend='redis://redis:6379/0',
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

@celery.task(bind=True, max_retries=3)
def process_data_task(self, items):
    """
    Process a batch of items
    Simulates heavy computation
    """
    try:
        results = []

        for item in items:
            # Simulate processing
            time.sleep(0.5)

            # TODO: add actual processing logic
            processed = {
                'original': item,
                'processed': item.upper() if isinstance(item, str) else str(item),
                'timestamp': time.time()
            }
            results.append(processed)

        return {
            'status': 'completed',
            'processed_count': len(results),
            'results': results
        }

    except Exception as exc:
        # Retry on failure
        raise self.retry(exc=exc, countdown=60)

@celery.task(bind=True, max_retries=3)
def fetch_external_data(self, url):
    """
    Fetch data from external API
    """
    try:
        # TODO: add timeout and proper error handling
        # TODO: add authentication headers
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        return {
            'status': 'success',
            'url': url,
            'status_code': response.status_code,
            'data': response.json() if 'application/json' in response.headers.get('content-type', '') else response.text[:500]
        }

    except requests.RequestException as exc:
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)

@celery.task
def cleanup_old_results():
    """
    Periodic task to clean up old results
    """
    # TODO: implement cleanup logic
    pass
