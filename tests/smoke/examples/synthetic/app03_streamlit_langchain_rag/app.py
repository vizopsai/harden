"""
Streamlit + LangChain RAG Application
Simple document Q&A with vector store
"""
import streamlit as st
from langchain.chat_models import ChatOpenAI
from langchain.vectorstores import FAISS
from langchain.embeddings import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.chains import RetrievalQA
import os

# Set page config
st.set_page_config(page_title="RAG Q&A", page_icon="🤖")

# Get API key from secrets
openai_api_key = st.secrets.get("openai_api_key", "")

# Initialize session state
if 'vectorstore' not in st.session_state:
    st.session_state.vectorstore = None

st.title("🤖 Document Q&A with RAG")
st.write("Upload documents and ask questions!")

# Sidebar for document upload
with st.sidebar:
    st.header("Document Upload")
    uploaded_file = st.file_uploader("Upload a text file", type=['txt'])

    if uploaded_file:
        # Read the file
        content = uploaded_file.read().decode('utf-8')

        # Split into chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200
        )
        chunks = text_splitter.split_text(content)

        # Create embeddings and vector store
        # TODO: add error handling for API failures
        embeddings = OpenAIEmbeddings(openai_api_key=openai_api_key)

        with st.spinner("Creating vector store..."):
            st.session_state.vectorstore = FAISS.from_texts(
                chunks,
                embeddings
            )

        st.success(f"Processed {len(chunks)} chunks!")

# Main chat interface
if st.session_state.vectorstore:
    question = st.text_input("Ask a question about your document:")

    if question:
        # Create LLM and QA chain
        llm = ChatOpenAI(
            temperature=0,
            model_name="gpt-3.5-turbo",
            openai_api_key=openai_api_key
        )

        # works fine for now, could optimize retriever settings
        qa_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=st.session_state.vectorstore.as_retriever(
                search_kwargs={"k": 3}
            )
        )

        with st.spinner("Thinking..."):
            try:
                response = qa_chain.run(question)
                st.write("### Answer:")
                st.write(response)
            except Exception as e:
                st.error(f"Error: {str(e)}")
                # TODO: add proper logging
else:
    st.info("👈 Please upload a document to get started!")

# Footer
st.divider()
st.caption("Built with Streamlit + LangChain + OpenAI")
