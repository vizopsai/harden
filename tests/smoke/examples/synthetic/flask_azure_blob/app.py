"""
Flask + Azure Blob Storage
File management service using Azure Storage
"""
from flask import Flask, request, jsonify, send_file
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient
from azure.identity import DefaultAzureCredential
import os
from io import BytesIO
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Initialize Azure Blob Service Client
# TODO: use managed identity instead of connection string
connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

if not connection_string:
    raise ValueError("AZURE_STORAGE_CONNECTION_STRING not found in environment")

blob_service_client = BlobServiceClient.from_connection_string(connection_string)

CONTAINER_NAME = "app-files"

# Ensure container exists
try:
    container_client = blob_service_client.get_container_client(CONTAINER_NAME)
    if not container_client.exists():
        container_client.create_container()
except Exception as e:
    print(f"Warning: Could not verify container: {e}")

@app.route('/')
def index():
    return jsonify({
        "message": "Azure Blob Storage API",
        "container": CONTAINER_NAME,
        "endpoints": {
            "/upload": "POST - Upload a file",
            "/files": "GET - List files",
            "/files/<filename>": "GET - Download file",
            "/files/<filename>": "DELETE - Delete file"
        }
    })

@app.route('/upload', methods=['POST'])
def upload_file():
    """
    Upload a file to Azure Blob Storage
    """
    # TODO: add authentication
    # TODO: validate file size and type

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'Empty filename'}), 400

    try:
        # Get blob client
        blob_client = blob_service_client.get_blob_client(
            container=CONTAINER_NAME,
            blob=file.filename
        )

        # Upload file
        blob_client.upload_blob(file, overwrite=True)

        # Get blob URL
        blob_url = blob_client.url

        return jsonify({
            'message': 'File uploaded successfully',
            'filename': file.filename,
            'url': blob_url,
            'container': CONTAINER_NAME
        }), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/files', methods=['GET'])
def list_files():
    """
    List all files in the container
    """
    try:
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)

        blob_list = []
        for blob in container_client.list_blobs():
            blob_list.append({
                'name': blob.name,
                'size': blob.size,
                'created': blob.creation_time.isoformat() if blob.creation_time else None,
                'last_modified': blob.last_modified.isoformat() if blob.last_modified else None,
                'content_type': blob.content_settings.content_type if blob.content_settings else None
            })

        return jsonify({
            'container': CONTAINER_NAME,
            'count': len(blob_list),
            'files': blob_list
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/files/<filename>', methods=['GET'])
def download_file(filename):
    """
    Download a file from Azure Blob Storage
    """
    try:
        blob_client = blob_service_client.get_blob_client(
            container=CONTAINER_NAME,
            blob=filename
        )

        if not blob_client.exists():
            return jsonify({'error': 'File not found'}), 404

        # Download blob content
        stream = BytesIO()
        blob_data = blob_client.download_blob()
        blob_data.readinto(stream)
        stream.seek(0)

        # Get content type
        properties = blob_client.get_blob_properties()
        content_type = properties.content_settings.content_type if properties.content_settings else 'application/octet-stream'

        return send_file(
            stream,
            mimetype=content_type,
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/files/<filename>', methods=['DELETE'])
def delete_file(filename):
    """
    Delete a file from Azure Blob Storage
    """
    # TODO: add proper authorization
    try:
        blob_client = blob_service_client.get_blob_client(
            container=CONTAINER_NAME,
            blob=filename
        )

        if not blob_client.exists():
            return jsonify({'error': 'File not found'}), 404

        blob_client.delete_blob()

        return jsonify({
            'message': 'File deleted successfully',
            'filename': filename
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/files/<filename>/metadata', methods=['GET'])
def get_file_metadata(filename):
    """
    Get file metadata without downloading
    """
    try:
        blob_client = blob_service_client.get_blob_client(
            container=CONTAINER_NAME,
            blob=filename
        )

        if not blob_client.exists():
            return jsonify({'error': 'File not found'}), 404

        properties = blob_client.get_blob_properties()

        return jsonify({
            'name': filename,
            'size': properties.size,
            'created': properties.creation_time.isoformat() if properties.creation_time else None,
            'last_modified': properties.last_modified.isoformat() if properties.last_modified else None,
            'content_type': properties.content_settings.content_type if properties.content_settings else None,
            'etag': properties.etag
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    """Health check"""
    try:
        # Check if we can access the container
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        container_client.exists()
        return jsonify({'status': 'ok', 'container': CONTAINER_NAME})
    except Exception as e:
        return jsonify({'status': 'error', 'detail': str(e)}), 500

if __name__ == '__main__':
    # TODO: use production WSGI server
    app.run(host='0.0.0.0', port=5000, debug=True)
