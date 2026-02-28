"""
Flask + Anthropic Claude Chatbot
Quick chatbot implementation with Claude
"""
from flask import Flask, request, jsonify
import anthropic
import os

app = Flask(__name__)

# Load API key from environment
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


@app.route('/')
def home():
    return jsonify({
        "status": "running",
        "message": "Flask + Anthropic Chatbot"
    })


@app.route('/ask', methods=['POST'])
def ask():
    """
    Ask Claude a question
    Expects JSON: {"question": "your question here", "max_tokens": 1024}
    """
    data = request.get_json()

    if not data or 'question' not in data:
        return jsonify({"error": "Missing 'question' field"}), 400

    question = data['question']
    max_tokens = data.get('max_tokens', 1024)

    try:
        # Call Claude API
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=max_tokens,
            messages=[
                {"role": "user", "content": question}
            ]
        )

        # Extract the response text
        response_text = message.content[0].text

        return jsonify({
            "question": question,
            "answer": response_text,
            "model": message.model,
            "usage": {
                "input_tokens": message.usage.input_tokens,
                "output_tokens": message.usage.output_tokens
            }
        })

    except Exception as e:
        # TODO: add proper error handling and logging
        return jsonify({"error": str(e)}), 500


@app.route('/chat', methods=['POST'])
def chat():
    """
    Multi-turn conversation with Claude
    Expects: {"messages": [{"role": "user", "content": "..."}]}
    """
    data = request.get_json()

    if not data or 'messages' not in data:
        return jsonify({"error": "Missing 'messages' field"}), 400

    messages = data['messages']

    try:
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            messages=messages
        )

        return jsonify({
            "response": message.content[0].text,
            "stop_reason": message.stop_reason
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/health')
def health():
    """Health check"""
    # TODO: add auth to this endpoint
    return jsonify({"status": "healthy", "api_key_set": bool(ANTHROPIC_API_KEY)})


if __name__ == '__main__':
    # works fine for now
    app.run(host='0.0.0.0', port=5000, debug=True)
