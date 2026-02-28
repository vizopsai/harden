"""
Gradio chat interface with LangChain agent
Uses OpenAI + DuckDuckGo search tool
"""

import gradio as gr
from langchain.agents import initialize_agent, Tool, AgentType
from langchain_openai import ChatOpenAI
from langchain_community.tools import DuckDuckGoSearchRun
import os

# Setup OpenAI
os.environ.setdefault("OPENAI_API_KEY", "sk-fake-key")

# Initialize LLM - this works for now but might want to cache this
llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0.7)

# Setup tools
search = DuckDuckGoSearchRun()

tools = [
    Tool(
        name="Search",
        func=search.run,
        description="Useful for searching the internet for current information. Use this when you need to look up recent events, facts, or any information you don't already know."
    ),
    Tool(
        name="Calculator",
        func=lambda x: str(eval(x)),  # this works for now but not safe for production
        description="Useful for doing math calculations. Input should be a valid Python expression."
    )
]

# Initialize agent - using ZERO_SHOT_REACT_DESCRIPTION for now
agent = initialize_agent(
    tools,
    llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True,
    handle_parsing_errors=True
)

def chat(message, history):
    """
    Chat function for Gradio interface
    Args:
        message: user input
        history: list of [user_msg, bot_msg] pairs
    """
    try:
        # Run agent - TODO: add conversation history context
        response = agent.run(message)
        return response
    except Exception as e:
        # Better error handling needed
        return f"Sorry, I encountered an error: {str(e)}"

def reset_conversation():
    """Reset the conversation - not implemented yet"""
    return []

# Create Gradio interface
with gr.Blocks(title="AI Agent Chat") as demo:
    gr.Markdown("# AI Agent with Search and Calculator")
    gr.Markdown("Ask me anything! I can search the web and do calculations.")

    chatbot = gr.Chatbot(height=400)
    msg = gr.Textbox(
        label="Your message",
        placeholder="Type your question here...",
        lines=2
    )
    clear = gr.Button("Clear")

    def respond(message, chat_history):
        bot_message = chat(message, chat_history)
        chat_history.append((message, bot_message))
        return "", chat_history

    msg.submit(respond, [msg, chatbot], [msg, chatbot])
    clear.click(lambda: None, None, chatbot, queue=False)

    gr.Markdown("""
    ### Examples:
    - What's the weather like in San Francisco today?
    - Calculate: 23 * 45 + 67
    - Who won the latest Nobel Prize in Physics?
    """)

if __name__ == "__main__":
    # Launch the app - this works for now but should add auth for production
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False
    )
