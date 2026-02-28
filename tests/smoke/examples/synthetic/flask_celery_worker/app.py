"""
Flask app with Celery background task processing
Handles data processing requests asynchronously
"""
from flask import Flask, request, jsonify
from tasks import process_data_task, fetch_external_data
import os

app = Flask(__name__)

# Simple in-memory task store
# TODO: replace with Redis or database for persistence
task_results = {}

@app.route('/')
def index():
    return jsonify({
        "message": "Celery Task API",
        "endpoints": {
            "/process": "POST - Queue a data processing task",
            "/fetch": "POST - Fetch data from external API",
            "/status/<task_id>": "GET - Check task status"
        }
    })

@app.route('/process', methods=['POST'])
def process_data():
    """
    Queue a background task to process data
    """
    data = request.get_json()

    if not data or 'items' not in data:
        return jsonify({'error': 'Missing items in request'}), 400

    # Queue the Celery task
    # TODO: add rate limiting
    task = process_data_task.delay(data['items'])

    return jsonify({
        'task_id': task.id,
        'status': 'queued',
        'message': 'Task queued for processing'
    }), 202

@app.route('/fetch', methods=['POST'])
def fetch_data():
    """
    Fetch data from an external API asynchronously
    """
    data = request.get_json()
    url = data.get('url')

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    # TODO: validate URL to prevent SSRF
    task = fetch_external_data.delay(url)

    return jsonify({
        'task_id': task.id,
        'status': 'queued',
        'message': 'Fetch task queued'
    }), 202

@app.route('/status/<task_id>')
def task_status(task_id):
    """
    Check the status of a Celery task
    """
    from tasks import celery
    task = celery.AsyncResult(task_id)

    if task.state == 'PENDING':
        response = {
            'state': task.state,
            'status': 'Task is waiting for execution'
        }
    elif task.state == 'FAILURE':
        response = {
            'state': task.state,
            'status': str(task.info)
        }
    else:
        response = {
            'state': task.state,
            'result': task.result
        }

    return jsonify(response)

@app.route('/health')
def health():
    """Health check"""
    # TODO: actually check Celery worker health
    return jsonify({'status': 'ok', 'workers': 'unknown'})

if __name__ == '__main__':
    # TODO: use gunicorn in production
    app.run(host='0.0.0.0', port=5000, debug=True)
