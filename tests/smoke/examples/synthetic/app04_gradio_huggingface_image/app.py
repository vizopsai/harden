"""
Gradio + HuggingFace Image Classification
Simple image classifier web interface
"""
import gradio as gr
from transformers import pipeline
import os
from PIL import Image

# Get HuggingFace token from environment
# TODO: add validation for token
HF_TOKEN = os.getenv("HF_TOKEN", "")

# Load the image classification model
# works fine for now, using default model
print("Loading image classification model...")
classifier = pipeline(
    "image-classification",
    model="google/vit-base-patch16-224",
    token=HF_TOKEN if HF_TOKEN else None
)
print("Model loaded successfully!")


def classify_image(image):
    """
    Classify an image and return top predictions
    """
    if image is None:
        return "Please upload an image"

    try:
        # Run classification
        results = classifier(image)

        # Format results
        output = "### Top Predictions:\n\n"
        for i, result in enumerate(results[:5], 1):
            label = result['label']
            score = result['score'] * 100
            output += f"{i}. **{label}** - {score:.2f}%\n"

        return output

    except Exception as e:
        # TODO: better error handling
        return f"Error: {str(e)}"


def predict_and_visualize(image):
    """
    Classify image and return formatted results
    """
    if image is None:
        return None, "Please upload an image"

    results = classifier(image)

    # Create formatted text output
    text_output = "Classification Results:\n\n"
    for i, result in enumerate(results[:5], 1):
        text_output += f"{i}. {result['label']}: {result['score']*100:.2f}%\n"

    return image, text_output


# Create Gradio interface
with gr.Blocks(title="Image Classifier") as demo:
    gr.Markdown("# 🖼️ Image Classification with HuggingFace")
    gr.Markdown("Upload an image to classify it using Vision Transformer")

    with gr.Row():
        with gr.Column():
            input_image = gr.Image(type="pil", label="Upload Image")
            classify_btn = gr.Button("Classify", variant="primary")

        with gr.Column():
            output_text = gr.Textbox(
                label="Results",
                lines=10,
                placeholder="Classification results will appear here..."
            )

    # Example images (optional)
    gr.Examples(
        examples=[],  # Add example image paths here if needed
        inputs=input_image
    )

    # Connect the button to the function
    classify_btn.click(
        fn=classify_image,
        inputs=input_image,
        outputs=output_text
    )

    gr.Markdown("---")
    gr.Markdown("Built with Gradio + HuggingFace Transformers")


if __name__ == "__main__":
    # TODO: add auth if deploying publicly
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False
    )
