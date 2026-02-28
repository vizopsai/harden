"""
Flask app with RabbitMQ and SendGrid for email notifications
"""

from flask import Flask, request, jsonify
import pika
import requests
import json
import os

app = Flask(__name__)

# Config from env - this works for now
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "SG.fake-key")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://user:REPLACE_ME@rabbitmq:5672")

def get_rabbitmq_connection():
    """Get RabbitMQ connection - TODO: add connection pooling"""
    try:
        params = pika.URLParameters(RABBITMQ_URL)
        connection = pika.BlockingConnection(params)
        return connection
    except Exception as e:
        print(f"Failed to connect to RabbitMQ: {e}")
        return None

def send_email_sendgrid(to_email, subject, content):
    """Send email via SendGrid API"""
    url = "https://api.sendgrid.com/v3/mail/send"
    headers = {
        "Authorization": f"Bearer {SENDGRID_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "personalizations": [{
            "to": [{"email": to_email}],
            "subject": subject
        }],
        "from": {"email": "notifications@example.com"},
        "content": [{
            "type": "text/plain",
            "value": content
        }]
    }

    # this works for now but needs retry logic
    response = requests.post(url, headers=headers, json=data)
    return response.status_code == 202

@app.route('/')
def home():
    return {"status": "notification service running"}

@app.route('/notify', methods=['POST'])
def notify():
    """
    Endpoint to send notifications
    Publishes to RabbitMQ and optionally sends immediate email
    """
    data = request.json

    if not data or 'email' not in data or 'message' not in data:
        return jsonify({"error": "Missing required fields"}), 400

    email = data['email']
    message = data['message']
    subject = data.get('subject', 'Notification')
    immediate = data.get('immediate', False)

    # Publish to RabbitMQ for async processing
    connection = get_rabbitmq_connection()
    if connection:
        try:
            channel = connection.channel()
            channel.queue_declare(queue='notifications', durable=True)

            notification_data = {
                "email": email,
                "subject": subject,
                "message": message
            }

            channel.basic_publish(
                exchange='',
                routing_key='notifications',
                body=json.dumps(notification_data),
                properties=pika.BasicProperties(
                    delivery_mode=2,  # make message persistent
                )
            )
            connection.close()
        except Exception as e:
            print(f"Failed to publish to RabbitMQ: {e}")

    # Send immediately if requested
    if immediate:
        try:
            success = send_email_sendgrid(email, subject, message)
            if not success:
                return jsonify({"error": "Failed to send email"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return jsonify({
        "status": "queued",
        "email": email,
        "immediate": immediate
    })

@app.route('/health')
def health():
    # Check RabbitMQ connection
    connection = get_rabbitmq_connection()
    rabbitmq_ok = connection is not None
    if connection:
        connection.close()

    return jsonify({
        "status": "healthy" if rabbitmq_ok else "degraded",
        "rabbitmq": rabbitmq_ok
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
