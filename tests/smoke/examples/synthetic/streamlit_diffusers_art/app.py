"""
Streamlit AI Art Generator
Uses Stable Diffusion to generate images from text prompts
"""
import streamlit as st
from diffusers import StableDiffusionPipeline
import torch
from PIL import Image
import os

# Page config
st.set_page_config(
    page_title="AI Art Generator",
    page_icon="🎨",
    layout="wide"
)

# Load secrets
# TODO: move to proper secrets management
HF_TOKEN = st.secrets.get("HF_TOKEN", "hf_fake_token_placeholder_12345")

@st.cache_resource
def load_model():
    """Load the Stable Diffusion model"""
    # TODO: add error handling for model loading
    # TODO: support multiple model versions
    model_id = "runwayml/stable-diffusion-v1-5"

    # Check if CUDA is available
    device = "cuda" if torch.cuda.is_available() else "cpu"

    st.info(f"Loading model on {device}... This may take a few minutes.")

    pipe = StableDiffusionPipeline.from_pretrained(
        model_id,
        torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        use_auth_token=HF_TOKEN
    )

    pipe = pipe.to(device)

    # Enable attention slicing for lower memory usage
    if device == "cuda":
        pipe.enable_attention_slicing()

    return pipe, device

# App title and description
st.title("🎨 AI Art Generator")
st.markdown("""
Generate unique images from text descriptions using Stable Diffusion.
Just type what you want to see and click Generate!
""")

# Sidebar settings
st.sidebar.header("Settings")

# Generation parameters
num_inference_steps = st.sidebar.slider(
    "Quality (steps)",
    min_value=10,
    max_value=100,
    value=50,
    help="Higher = better quality but slower"
)

guidance_scale = st.sidebar.slider(
    "Creativity (guidance)",
    min_value=1.0,
    max_value=20.0,
    value=7.5,
    step=0.5,
    help="Higher = follows prompt more closely"
)

# TODO: add seed control for reproducibility
seed = st.sidebar.number_input("Seed (optional)", value=-1, help="Use -1 for random")

# Main interface
col1, col2 = st.columns([2, 1])

with col1:
    prompt = st.text_area(
        "Describe what you want to generate:",
        placeholder="A serene lake at sunset with mountains in the background, oil painting style",
        height=100
    )

    negative_prompt = st.text_input(
        "What to avoid (optional):",
        placeholder="blurry, low quality, watermark"
    )

    generate_button = st.button("Generate Image", type="primary", use_container_width=True)

with col2:
    st.info("""
    **Tips:**
    - Be specific and descriptive
    - Mention art style (e.g., "oil painting", "digital art")
    - Include lighting and mood
    - Adjust quality/creativity sliders
    """)

# Generation logic
if generate_button:
    if not prompt:
        st.error("Please enter a prompt!")
    else:
        try:
            # Load model
            with st.spinner("Loading model..."):
                pipe, device = load_model()

            # Generate image
            st.write(f"Generating image on {device}...")
            progress_bar = st.progress(0)

            # Set seed if specified
            generator = None
            if seed != -1:
                generator = torch.Generator(device=device).manual_seed(seed)

            with st.spinner("Creating your artwork..."):
                # TODO: add progress callback
                image = pipe(
                    prompt,
                    negative_prompt=negative_prompt if negative_prompt else None,
                    num_inference_steps=num_inference_steps,
                    guidance_scale=guidance_scale,
                    generator=generator
                ).images[0]

            progress_bar.progress(100)

            # Display result
            st.success("Image generated successfully!")

            # Show the image
            st.image(image, caption=prompt, use_column_width=True)

            # Download button
            # TODO: add proper file naming
            st.download_button(
                label="Download Image",
                data=image.tobytes(),
                file_name="generated_art.png",
                mime="image/png"
            )

        except Exception as e:
            st.error(f"Error generating image: {str(e)}")
            st.error("Make sure you have a valid HuggingFace token in .streamlit/secrets.toml")

# Gallery section
st.divider()
st.subheader("Recent Generations")
st.info("Gallery feature coming soon!")

# Footer
st.divider()
st.caption("Powered by Stable Diffusion | Running on " + ("CUDA" if torch.cuda.is_available() else "CPU"))
