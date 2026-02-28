"""
Flask + AWS S3 File Upload
Simple file upload service using S3
"""
from flask import Flask, request, jsonify
import boto3
from werkzeug.utils import secure_filename
import os
from datetime import datetime

app = Flask(__name__)

# AWS credentials - TODO: move to environment variables
AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
AWS_REGION = "us-west-2"
S3_BUCKET = "my-app-uploads"

# Initialize S3 client
s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION
)

# Allowed file extensions
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx'}


def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/')
def home():
    return jsonify({
        "status": "running",
        "message": "S3 File Upload Service",
        "bucket": S3_BUCKET
    })


@app.route('/upload', methods=['POST'])
def upload_file():
    """
    Upload a file to S3
    Expects multipart/form-data with 'file' field
    """
    # Check if file is in request
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']

    # Check if file is selected
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    # Validate file extension
    if not allowed_file(file.filename):
        return jsonify({
            "error": "File type not allowed",
            "allowed_types": list(ALLOWED_EXTENSIONS)
        }), 400

    try:
        # Secure the filename
        filename = secure_filename(file.filename)

        # Add timestamp to avoid collisions - works fine for now
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        s3_key = f"uploads/{timestamp}_{filename}"

        # Upload to S3
        s3_client.upload_fileobj(
            file,
            S3_BUCKET,
            s3_key,
            ExtraArgs={
                'ContentType': file.content_type or 'application/octet-stream'
            }
        )

        # Generate the file URL
        file_url = f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{s3_key}"

        return jsonify({
            "message": "File uploaded successfully",
            "filename": filename,
            "s3_key": s3_key,
            "url": file_url
        }), 201

    except Exception as e:
        # TODO: add proper error logging
        return jsonify({"error": str(e)}), 500


@app.route('/list', methods=['GET'])
def list_files():
    """
    List files in the S3 bucket
    TODO: add pagination
    """
    try:
        response = s3_client.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix='uploads/',
            MaxKeys=100
        )

        files = []
        if 'Contents' in response:
            for obj in response['Contents']:
                files.append({
                    "key": obj['Key'],
                    "size": obj['Size'],
                    "last_modified": obj['LastModified'].isoformat()
                })

        return jsonify({
            "bucket": S3_BUCKET,
            "files": files,
            "count": len(files)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy"})


if __name__ == '__main__':
    # works fine for now
    app.run(host='0.0.0.0', port=5000, debug=True)
