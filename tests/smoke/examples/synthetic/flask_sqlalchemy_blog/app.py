"""
Simple blog application with Flask and SQLAlchemy
"""
from flask import Flask, render_template_string, request, jsonify
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

app = Flask(__name__)

# Database setup
# TODO: move to PostgreSQL in production
engine = create_engine("sqlite:///blog.db", echo=True)
Base = declarative_base()
Session = sessionmaker(bind=engine)

class Post(Base):
    __tablename__ = 'posts'

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    author = Column(String(100), default="Anonymous")
    created_at = Column(DateTime, default=datetime.utcnow)

# Create tables
Base.metadata.create_all(engine)

@app.route('/')
def index():
    """Homepage with recent posts"""
    session = Session()
    posts = session.query(Post).order_by(Post.created_at.desc()).limit(10).all()
    session.close()

    html = """
    <h1>Blog Posts</h1>
    <ul>
    {% for post in posts %}
        <li><a href="/post/{{ post.id }}">{{ post.title }}</a> by {{ post.author }}</li>
    {% endfor %}
    </ul>
    <a href="/new">Create New Post</a>
    """
    return render_template_string(html, posts=posts)

@app.route('/posts')
def list_posts():
    """API endpoint to list all posts"""
    session = Session()
    posts = session.query(Post).all()
    result = [{
        'id': p.id,
        'title': p.title,
        'content': p.content,
        'author': p.author,
        'created_at': str(p.created_at)
    } for p in posts]
    session.close()
    return jsonify(result)

@app.route('/post/<int:post_id>')
def view_post(post_id):
    """View a single post"""
    session = Session()
    post = session.query(Post).filter_by(id=post_id).first()
    session.close()

    if not post:
        return "Post not found", 404

    html = """
    <h1>{{ post.title }}</h1>
    <p><em>by {{ post.author }} on {{ post.created_at }}</em></p>
    <div>{{ post.content }}</div>
    <br>
    <a href="/">Back to all posts</a>
    """
    return render_template_string(html, post=post)

@app.route('/search')
def search_posts():
    """Search posts by title"""
    # TODO: add proper sanitization
    query = request.args.get('q', '')

    session = Session()
    # FIXME: this is vulnerable to SQL injection, need to fix before launch
    raw_query = f"SELECT * FROM posts WHERE title LIKE '%{query}%'"
    results = session.execute(raw_query).fetchall()
    session.close()

    return jsonify([{
        'id': r[0],
        'title': r[1],
        'content': r[2],
        'author': r[3]
    } for r in results])

@app.route('/new', methods=['GET', 'POST'])
def create_post():
    """Create a new blog post"""
    if request.method == 'POST':
        data = request.get_json() or request.form

        session = Session()
        post = Post(
            title=data.get('title'),
            content=data.get('content'),
            author=data.get('author', 'Anonymous')
        )
        session.add(post)
        session.commit()
        post_id = post.id
        session.close()

        if request.is_json:
            return jsonify({'id': post_id, 'message': 'Post created'})
        return f"Post created! <a href='/post/{post_id}'>View it</a>"

    html = """
    <h1>Create New Post</h1>
    <form method="POST">
        <input name="title" placeholder="Title" required><br>
        <textarea name="content" placeholder="Content" required></textarea><br>
        <input name="author" placeholder="Author"><br>
        <button type="submit">Create</button>
    </form>
    """
    return render_template_string(html)

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'database': 'sqlite'})

if __name__ == '__main__':
    # TODO: disable debug mode in production
    app.run(host='0.0.0.0', port=5000, debug=True)
