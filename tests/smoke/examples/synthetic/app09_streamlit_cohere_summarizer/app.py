"""
Streamlit + Cohere Text Summarizer
Simple text summarization app using Cohere's API
"""
import streamlit as st
import cohere
import os

# Page config
st.set_page_config(
    page_title="Text Summarizer",
    page_icon="📝",
    layout="wide"
)

# Get Cohere API key
COHERE_API_KEY = os.getenv("COHERE_API_KEY", "")

# Initialize Cohere client
# works fine for now
co = cohere.Client(COHERE_API_KEY)

# Title and description
st.title("📝 Text Summarizer")
st.markdown("Summarize long texts using Cohere's AI")

# Sidebar settings
with st.sidebar:
    st.header("Settings")

    length_option = st.selectbox(
        "Summary Length",
        ["short", "medium", "long"],
        index=1
    )

    format_option = st.selectbox(
        "Format",
        ["paragraph", "bullets"],
        index=0
    )

    temperature = st.slider(
        "Temperature (creativity)",
        min_value=0.0,
        max_value=1.0,
        value=0.3,
        step=0.1
    )

    st.divider()
    st.caption("Powered by Cohere")

# Main content area
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Input Text")
    input_text = st.text_area(
        "Enter text to summarize:",
        height=400,
        placeholder="Paste your text here...",
        help="Enter the text you want to summarize"
    )

    summarize_button = st.button("✨ Summarize", type="primary", use_container_width=True)

with col2:
    st.subheader("Summary")

    if summarize_button:
        if not input_text.strip():
            st.warning("Please enter some text to summarize!")
        elif not COHERE_API_KEY:
            st.error("Cohere API key not found. Please set COHERE_API_KEY environment variable.")
        else:
            try:
                with st.spinner("Generating summary..."):
                    # Call Cohere summarize endpoint
                    response = co.summarize(
                        text=input_text,
                        length=length_option,
                        format=format_option,
                        temperature=temperature,
                        extractiveness='medium'
                    )

                    summary = response.summary

                    # Display summary
                    st.markdown(f"**Summary ({length_option}, {format_option}):**")
                    st.write(summary)

                    # Show metadata
                    with st.expander("📊 Details"):
                        st.write(f"**Original length:** {len(input_text.split())} words")
                        st.write(f"**Summary length:** {len(summary.split())} words")
                        st.write(f"**Compression ratio:** {len(summary.split())/len(input_text.split()):.2%}")

                    # TODO: add option to download summary

            except Exception as e:
                st.error(f"Error: {str(e)}")
                # TODO: add better error handling and logging

# Example texts
with st.expander("📖 Try Example Texts"):
    example_text = """
    Artificial intelligence (AI) is intelligence demonstrated by machines, as opposed to
    natural intelligence displayed by animals including humans. Leading AI textbooks define
    the field as the study of "intelligent agents": any system that perceives its environment
    and takes actions that maximize its chance of achieving its goals. Some popular accounts
    use the term "artificial intelligence" to describe machines that mimic "cognitive" functions
    that humans associate with the human mind, such as "learning" and "problem solving", however,
    this definition is rejected by major AI researchers.

    AI applications include advanced web search engines, recommendation systems, understanding
    human speech, self-driving cars, automated decision-making and competing at the highest
    level in strategic game systems. As machines become increasingly capable, tasks considered
    to require "intelligence" are often removed from the definition of AI, a phenomenon known
    as the AI effect. For instance, optical character recognition is frequently excluded from
    things considered to be AI, having become a routine technology.
    """

    if st.button("Load Example Text"):
        st.session_state['example_loaded'] = True
        st.rerun()

# Footer
st.divider()
st.caption("Built with Streamlit + Cohere AI")
