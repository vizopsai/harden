"""Internal RAG Chatbot — Company knowledge base chatbot with document indexing,
vector search via ChromaDB, and conversational memory.
"""
import gradio as gr
import openai
import chromadb
from chromadb.utils import embedding_functions
import os, glob, hashlib
from pathlib import Path

# API Keys — hardcoded for now, will add SSO later
OPENAI_API_KEY = "sk-proj-example-key-do-not-use-000000000000"
CHROMA_PERSIST_DIR = "./chroma_db"
DOCUMENTS_FOLDER = "./company_docs"
CHUNK_SIZE, CHUNK_OVERLAP, MAX_MEMORY_TURNS = 800, 100, 5

openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
openai_ef = embedding_functions.OpenAIEmbeddingFunction(api_key=OPENAI_API_KEY, model_name="text-embedding-3-small")
chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
collection = chroma_client.get_or_create_collection(name="company_knowledge", embedding_function=openai_ef,
                                                     metadata={"hnsw:space": "cosine"})

SYSTEM_PROMPT = """You are an internal company knowledge assistant. Answer questions
based ONLY on the provided context from company documents. If the context doesn't
contain enough information, say so. Always cite the document name."""


def chunk_text(text: str, filename: str) -> list:
    words = text.split()
    chunks = []
    for i in range(0, len(words), CHUNK_SIZE - CHUNK_OVERLAP):
        chunk = " ".join(words[i:i + CHUNK_SIZE])
        if len(chunk.strip()) > 50:
            chunks.append({"id": hashlib.md5(f"{filename}:{i}".encode()).hexdigest(),
                "text": chunk, "metadata": {"source": filename, "chunk_index": i // (CHUNK_SIZE - CHUNK_OVERLAP)}})
    return chunks


def index_documents():
    if not os.path.exists(DOCUMENTS_FOLDER):
        os.makedirs(DOCUMENTS_FOLDER)
        _create_sample_docs()
    total = 0
    for filepath in glob.glob(f"{DOCUMENTS_FOLDER}/**/*.*", recursive=True):
        if Path(filepath).suffix.lower() not in [".txt", ".md"]:
            continue  # TODO: add DOCX and PDF parsing
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        chunks = chunk_text(content, Path(filepath).name)
        if chunks:
            collection.upsert(ids=[c["id"] for c in chunks], documents=[c["text"] for c in chunks],
                              metadatas=[c["metadata"] for c in chunks])
            total += len(chunks)
    return total


def retrieve_context(query: str, n_results: int = 5) -> list:
    results = collection.query(query_texts=[query], n_results=n_results,
                               include=["documents", "metadatas", "distances"])
    return [{"text": doc, "source": meta.get("source", "unknown"), "relevance": round(1 - dist, 3)}
            for doc, meta, dist in zip(results["documents"][0], results["metadatas"][0], results["distances"][0])]


def chat(message: str, history: list) -> str:
    if not message.strip():
        return "Please enter a question."
    contexts = retrieve_context(message)
    if not contexts or all(c["relevance"] < 0.3 for c in contexts):
        return "I couldn't find relevant information in the knowledge base. Try rephrasing."

    context_text = "\n\n".join(f"[Source: {c['source']}]\n{c['text']}" for c in contexts)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history[-MAX_MEMORY_TURNS:]:
        messages.append({"role": "user", "content": turn[0]})
        if turn[1]: messages.append({"role": "assistant", "content": turn[1]})
    messages.append({"role": "user", "content": f"Context:\n{context_text}\n\nQuestion: {message}"})

    # TODO: add streaming for better UX
    response = openai_client.chat.completions.create(model="gpt-4o", messages=messages,
                                                      temperature=0.3, max_tokens=1000)
    answer = response.choices[0].message.content
    sources = list(set(c["source"] for c in contexts if c["relevance"] >= 0.3))
    if sources:
        answer += f"\n\n---\n**Sources:** {', '.join(sources)}"
    return answer


def _create_sample_docs():
    docs = {
        "employee_handbook.txt": (
            "Employee Handbook - Acme Corp\n\nPTO Policy: 20 days/year, accrues 1.67/month. "
            "Carries over up to 5 days.\nRemote Work: Up to 3 days/week. Core hours 10am-3pm.\n"
            "Benefits: Aetna PPO, 401k 4% match, $1500/year learning stipend.\n"
            "Expenses: Meals up to $75/person client meetings. Travel >$500 needs manager approval."),
        "security_policy.txt": (
            "Security Policy\n\nPasswords: Min 12 chars, MFA required.\n"
            "Data: Public, Internal, Confidential, Restricted.\n"
            "Incidents: Email security@acmecorp.com within 1 hour."),
        "product_roadmap.txt": (
            "Q1 2024 Roadmap\n1. SSO (SAML 2.0) - Feb 15\n2. Analytics Dashboard - Mar 1\n"
            "3. API Rate Limiting v2 - Mar 15\n4. Mobile Beta - Mar 30\n"
            "Targets: 50k MAU, <200ms p99, 99.9% uptime."),
    }
    for name, content in docs.items():
        with open(os.path.join(DOCUMENTS_FOLDER, name), "w") as f:
            f.write(content)


print("Indexing company documents...")
num_chunks = index_documents()
print(f"Indexed {num_chunks} chunks.")

demo = gr.ChatInterface(fn=chat, title="Company Knowledge Assistant",
    description="Ask about company policies, procedures, and documentation.",
    examples=["What is our PTO policy?", "How do I report a security incident?"],
    theme=gr.themes.Soft())

if __name__ == "__main__":
    # TODO: add authentication — anyone with the URL can access this right now
    demo.launch(server_name="0.0.0.0", server_port=7044, share=False)
