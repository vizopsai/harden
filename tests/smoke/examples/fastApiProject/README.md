# FastAPI Application

This is a simple chatbot and stock price checker application built with FastAPI. The chat function uses OpenAI GPT API and the stock function uses Alpha Vantage API.

## Prerequisites

- Python 3.8 or higher
- Pip (Python package installer)

## Setup

1. **Clone the repository**:
    ```sh
    git clone https://github.com/Joefilas/fastApiProject.git
    cd fastApiProject
    ```

2. **Create a virtual environment**:
    ```sh
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3. **Install dependencies**:
    ```sh
    pip install -r requirements.txt
    ```

4. **Create a `.env` file**:
    Create a file named `.env` in the root directory of your project and add your OpenAI API key and Alpha Vantage API key:
    ```
    OPENAI_API_KEY=your-openai-api-key
    ALPHA_VANTAGE_API_KEY=your-alphavantage-api-key
    ```
   You can view or generate an OpenAI ChatGPT API key from `https://platform.openai.com/api-keys` by logging into your OpenAI account.
   <br>
   <br>
   You can generate a free Alpha Vantage API key from `https://www.alphavantage.co/support/#api-key`.


5. **Run the application**:
    ```sh
    python main.py
    ```

6. **Access the application**:

    Open your web browser and go to `http://127.0.0.1:8000/chat` to use the chatbot.
    <br>
    Open your web browser and go to `http://127.0.0.1:8000/stock` to use the stock price checker.
    

## Approach and Assumptions

### Approach:
#### Chat Function

1. **Initial Setup and Testing**:
   - Started by creating the endpoints in `main.py` for the chat functionality.
   - Tested these endpoints using mock inputs in Postman to ensure they were working correctly.

2. **Front-End Integration**:
   - Developed a simple HTML and JavaScript page to display a form for user input and to show the output.
   - Initially, the front-end used mock inputs and simply echoed the input as the output for testing purposes.

3. **API Integration**:
   - Integrated the ChatGPT API, replacing the mock inputs and outputs with real data from the API.

4. **Final Enhancements**:
   - Added CSS to enhance the visual appearance of the chat interface.
   
#### Stock Function
1. **Initial Setup and Testing**:
   - Followed the same approach as the Chat Function by creating the endpoints in `main.py` for the stock functionality.
   - Tested these endpoints with mock inputs using Postman to verify functionality.

2. **Front-End Integration**:
   - Created a basic HTML and JavaScript page to provide a form for user input and display the output.
   - Used mock inputs initially, echoing the input for output to ensure the front-end was working correctly.

3. **API Integration**:
   - Integrated the Alpha Vantage API to replace the mock inputs and outputs with real data from the API.

4. **Final Enhancements**:
   - Added CSS to enhance the visual appearance of the stock interface.

### Assumptions:
#### Chat Function
- Will only be used for text
- User has their own OpenAPI ChatGPT API key

#### Stock Function
- User has their own Alpha Vantage API key 

