"""
Flask + MSAL + Microsoft Graph
Authentication and Microsoft Graph API integration
"""
from flask import Flask, request, jsonify, session, redirect, url_for
from msal import ConfidentialClientApplication
import requests
import os
from dotenv import load_dotenv
from functools import wraps

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-in-prod")

# MSAL Configuration
# TODO: move to Azure Key Vault
CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "fake-client-id-12345")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "fake-secret")
TENANT_ID = os.getenv("AZURE_TENANT_ID", "fake-tenant-id")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
REDIRECT_URI = "http://localhost:5000/auth/callback"

# Microsoft Graph API
GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"
SCOPES = ["User.Read", "Mail.Read"]

# Initialize MSAL app
msal_app = ConfidentialClientApplication(
    CLIENT_ID,
    authority=AUTHORITY,
    client_credential=CLIENT_SECRET
)

def require_auth(f):
    """Decorator to require authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'access_token' not in session:
            return jsonify({'error': 'Not authenticated'}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return jsonify({
        "message": "Microsoft Graph API Integration",
        "authenticated": 'access_token' in session,
        "endpoints": {
            "/login": "GET - Start authentication flow",
            "/profile": "GET - Get user profile (requires auth)",
            "/emails": "GET - Get user emails (requires auth)",
            "/logout": "GET - Logout"
        }
    })

@app.route('/login')
def login():
    """
    Initiate OAuth2 login flow
    """
    # Generate authorization URL
    auth_url = msal_app.get_authorization_request_url(
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )

    return redirect(auth_url)

@app.route('/auth/callback')
def auth_callback():
    """
    Handle OAuth2 callback
    """
    # Get authorization code from query params
    code = request.args.get('code')

    if not code:
        return jsonify({'error': 'No authorization code received'}), 400

    try:
        # Exchange code for token
        result = msal_app.acquire_token_by_authorization_code(
            code,
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI
        )

        if "access_token" in result:
            # Store in session
            session['access_token'] = result['access_token']
            session['user_id'] = result.get('id_token_claims', {}).get('oid')

            return jsonify({
                'message': 'Authentication successful',
                'user_id': session['user_id']
            })
        else:
            return jsonify({'error': result.get('error_description', 'Authentication failed')}), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/profile')
@require_auth
def get_profile():
    """
    Get user profile from Microsoft Graph
    """
    # TODO: cache user profile data
    access_token = session['access_token']

    try:
        response = requests.get(
            f"{GRAPH_ENDPOINT}/me",
            headers={'Authorization': f'Bearer {access_token}'}
        )

        if response.status_code == 200:
            profile = response.json()
            return jsonify({
                'displayName': profile.get('displayName'),
                'mail': profile.get('mail'),
                'jobTitle': profile.get('jobTitle'),
                'officeLocation': profile.get('officeLocation'),
                'mobilePhone': profile.get('mobilePhone')
            })
        else:
            return jsonify({'error': 'Failed to fetch profile', 'details': response.text}), response.status_code

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/emails')
@require_auth
def get_emails():
    """
    Get user's recent emails
    """
    # TODO: add pagination support
    access_token = session['access_token']
    limit = request.args.get('limit', 10, type=int)

    try:
        response = requests.get(
            f"{GRAPH_ENDPOINT}/me/messages",
            headers={'Authorization': f'Bearer {access_token}'},
            params={
                '$top': limit,
                '$select': 'subject,from,receivedDateTime,bodyPreview'
            }
        )

        if response.status_code == 200:
            messages = response.json().get('value', [])

            emails = []
            for msg in messages:
                emails.append({
                    'subject': msg.get('subject'),
                    'from': msg.get('from', {}).get('emailAddress', {}).get('address'),
                    'received': msg.get('receivedDateTime'),
                    'preview': msg.get('bodyPreview')
                })

            return jsonify({
                'count': len(emails),
                'emails': emails
            })
        else:
            return jsonify({'error': 'Failed to fetch emails'}), response.status_code

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/calendar')
@require_auth
def get_calendar():
    """
    Get user's calendar events
    """
    # TODO: add date range filtering
    access_token = session['access_token']

    try:
        response = requests.get(
            f"{GRAPH_ENDPOINT}/me/calendar/events",
            headers={'Authorization': f'Bearer {access_token}'},
            params={
                '$top': 20,
                '$select': 'subject,start,end,location'
            }
        )

        if response.status_code == 200:
            events = response.json().get('value', [])

            return jsonify({
                'count': len(events),
                'events': events
            })
        else:
            return jsonify({'error': 'Failed to fetch calendar'}), response.status_code

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/logout')
def logout():
    """
    Logout user
    """
    session.clear()
    return jsonify({'message': 'Logged out successfully'})

@app.route('/health')
def health():
    """Health check"""
    return jsonify({
        'status': 'ok',
        'msal_configured': bool(CLIENT_ID and CLIENT_SECRET),
        'authenticated': 'access_token' in session
    })

if __name__ == '__main__':
    # TODO: use production WSGI server
    app.run(host='0.0.0.0', port=5000, debug=True)
