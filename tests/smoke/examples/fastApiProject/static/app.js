var stockFormElement = document.getElementById('stockForm');
if (stockFormElement) {
    stockFormElement.addEventListener('submit', function(event) {
        event.preventDefault();

        // Get the ticker value
        var ticker = document.getElementById('ticker').value;
        if(!ticker){
            document.getElementById('tickerResponse').innerText = `Provide a ticker`;
        }else{
            // Make an AJAX request to the server
            var xhr = new XMLHttpRequest();
            xhr.open('GET', '/stock_price?ticker=' + ticker, true);
            xhr.onreadystatechange = function() {
                var response = JSON.parse(xhr.responseText);
                if (xhr.readyState === XMLHttpRequest.DONE && xhr.status === 200) {
                    // If the request is successful, update the tickerResponse div with the response
                    document.getElementById('tickerResponse').innerText = `Price of ${response.stock_name}: $${response.price}`;
                } else{
                    // If the request is unsuccessful, update the tickerResponse div with the response
                    document.getElementById('tickerResponse').innerText = `${response.error}`;
                }
            };
            xhr.send();
        }


    });
} else {
    console.error("Element with ID 'stockForm' not found.");
}

function addMessageToConversation(message, isUser) {
    const conversationElement = document.getElementById('conversation');
    const messageElement = document.createElement('div');
    messageElement.classList.add('message');
    if (isUser) {
        messageElement.classList.add('user-message');
    } else {
        messageElement.classList.add('bot-message');
    }
    messageElement.textContent = message;
    conversationElement.appendChild(messageElement);
    // Scroll to the bottom of the conversation
    conversationElement.scrollTop = conversationElement.scrollHeight;
}


document.getElementById('chatForm').addEventListener('submit', async function(event) {
    event.preventDefault();
    const messageInput = document.getElementById('message');
    const message = messageInput.value.trim();
    if (message === '') return;

    // Add user's message to the conversation
    addMessageToConversation(message, true);

    // Make API call to get bot's response
    const response = await fetch('/chat', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ text: message })
    });
    const responseData = await response.json();

    // Add bot's response to the conversation
    addMessageToConversation(responseData.text, false);

    // Clear the input field
    messageInput.value = '';
});

