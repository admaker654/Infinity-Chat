from flask import Flask, request, jsonify, render_template, session, Response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import requests
from bs4 import BeautifulSoup
from together import Together
import os
import json
from dotenv import load_dotenv
import logging
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
import uuid

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set up rate limiting
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"]
)

# Configure SQLAlchemy
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'fallback_secret_key_for_development')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///users.db')
db = SQLAlchemy(app)

# Get the API key from the environment variable
together_api_key = os.getenv('TOGETHER_API_KEY')
if not together_api_key:
    raise ValueError("No Together API key set for TOGETHER_API_KEY")

client = Together(api_key=together_api_key)

# Store extracted text for each API key
extracted_texts = {}

# User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    api_keys = db.Column(db.Text)  # Store as JSON string

def extract_text_from_url(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    return ' '.join([p.text for p in soup.find_all('p')])

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 400
    
    hashed_password = generate_password_hash(password)
    new_user = User(email=email, password=hashed_password, api_keys='[]')
    db.session.add(new_user)
    db.session.commit()
    
    return jsonify({"message": "User registered successfully"}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    user = User.query.filter_by(email=email).first()
    if user and check_password_hash(user.password, password):
        session['user_id'] = user.id
        return jsonify({"message": "Logged in successfully"}), 200
    
    return jsonify({"error": "Invalid credentials"}), 401

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return jsonify({"message": "Logged out successfully"}), 200

@app.route('/process_url', methods=['POST'])
@limiter.limit("5 per minute")
def process_url():
    if 'user_id' not in session:
        return jsonify({"error": "User not logged in"}), 401

    url = request.json.get('url')
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        extracted_text = extract_text_from_url(url)
        api_key = f"user_{uuid.uuid4().hex}"
        extracted_texts[api_key] = extracted_text

        user = User.query.get(session['user_id'])
        api_keys = json.loads(user.api_keys)
        api_keys.append(api_key)
        user.api_keys = json.dumps(api_keys)
        db.session.commit()

        integration_code = generate_integration_script(api_key)

        response_data = {
            "message": "Processing complete",
            "api_key": api_key,
            "integration_code": integration_code
        }
        logger.info(f"Sending response: {response_data}")
        return jsonify(response_data)
    except Exception as e:
        logger.error(f"Error in process_url: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

def generate_integration_script(api_key):
    return f'''
<script>
(function() {{
    var script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/axios/dist/axios.min.js';
    script.onload = function() {{
        var chatbotScript = document.createElement('script');
        chatbotScript.textContent = `
            axios.get('https://chatcat-s1ny.onrender.com/chatbot-design?api_key={api_key}')
                .then(function(response) {{
                    var div = document.createElement('div');
                    div.innerHTML = response.data;
                    document.body.appendChild(div);
                }})
                .catch(function(error) {{
                    console.error('Error loading chatbot:', error);
                }});
        `;
        document.body.appendChild(chatbotScript);
    }};
    document.body.appendChild(script);
}})();
</script>
'''

@app.route('/chatbot-design', methods=['GET'])
def chatbot_design():
    api_key = request.args.get('api_key')
    if not api_key:
        return jsonify({"error": "API key is required"}), 400

    design = f'''
    <!-- AI Chatbot -->
    <div id="ai-chatbot" style="position: fixed; bottom: 20px; right: 20px; width: 300px; height: 400px; background-color: #f1f1f1; border-radius: 10px; box-shadow: 0 0 10px rgba(0,0,0,0.1); display: flex; flex-direction: column; overflow: hidden;">
        <div style="background-color: #007bff; color: white; padding: 10px; font-weight: bold;">AI Chatbot</div>
        <div id="chat-messages" style="flex-grow: 1; overflow-y: auto; padding: 10px;"></div>
        <div style="padding: 10px; border-top: 1px solid #ddd;">
            <input type="text" id="user-input" placeholder="Type your message..." style="width: 80%; padding: 5px;">
            <button onclick="sendMessage()" style="width: 18%; padding: 5px;">Send</button>
        </div>
    </div>

    <script>
    console.log('Chatbot script loaded');
    const chatWithAI = async (input) => {{
        console.log('Sending message to AI:', input);
        try {{
            const response = await axios.post('https://chatcat-s1ny.onrender.com/chat', {{
                input: input,
                api_key: '{api_key}'
            }});
            console.log('Received response from AI:', response.data);
            return response.data.response;
        }} catch (error) {{
            console.error('Error in chatWithAI:', error);
            if (error.response) {{
                console.error('Error response:', error.response.data);
                return `Server Error: ${{error.response.data.error || 'Unknown server error'}}`;
            }} else if (error.request) {{
                console.error('No response received');
                return 'Network Error: No response received from the server. Please check your internet connection.';
            }} else {{
                console.error('Error message:', error.message);
                return `Error: ${{error.message}}`;
            }}
        }}
    }};

    function addMessage(sender, message) {{
        console.log(`Adding message from ${{sender}}:`, message);
        const chatMessages = document.getElementById('chat-messages');
        const messageElement = document.createElement('div');
        messageElement.innerHTML = `<strong>${{sender}}:</strong> ${{message}}`;
        chatMessages.appendChild(messageElement);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }}

    async function sendMessage() {{
        const userInput = document.getElementById('user-input');
        const message = userInput.value.trim();
        if (message) {{
            console.log('User sending message:', message);
            addMessage('You', message);
            userInput.value = '';
            const response = await chatWithAI(message);
            console.log('Received AI response:', response);
            addMessage('AI', response);
        }}
    }}

    // Initialize chat
    console.log('Initializing chat');
    addMessage('AI', 'Hello! How can I assist you today?');

    // Add event listener for Enter key
    document.getElementById('user-input').addEventListener('keypress', function(event) {{
        if (event.key === 'Enter') {{
            sendMessage();
        }}
    }});
    </script>
    '''
    
    return Response(design, mimetype='text/html')

@app.route('/chat', methods=['POST'])
@limiter.limit("5 per minute")
def chat():
    try:
        user_input = request.json.get('input')
        api_key = request.json.get('api_key')

        if not user_input or not api_key:
            return jsonify({"error": "Input and API key are required"}), 400

        context = extracted_texts.get(api_key, "No context available for this API key.")

        messages = [{
            "role": "system",
            "content": f"You are a chatbot trained on the following website content: {context}"
        }, {
            "role": "user",
            "content": user_input
        }]

        logger.info(f"Sending request to Together API with input: {user_input}")
        response = client.chat.completions.create(
            model="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
            messages=messages,
            max_tokens=512,
            temperature=0.7,
            top_p=0.7,
            top_k=50,
            repetition_penalty=1,
            stop=["<|eot_id|>", "<|eom_id|>"])
        logger.info(f"Received response from Together API: {response}")

        return jsonify({"response": response.choices[0].message.content})
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error in chat route: {str(e)}", exc_info=True)
        return jsonify({"error": f"Network error: {str(e)}"}), 503
    except Together.APIError as e:
        logger.error(f"Together API error in chat route: {str(e)}", exc_info=True)
        return jsonify({"error": f"Together API error: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"Unexpected error in chat route: {str(e)}", exc_info=True)
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

@app.route('/user/api_keys', methods=['GET'])
def get_user_api_keys():
    if 'user_id' not in session:
        return jsonify({"error": "User not logged in"}), 401

    user = User.query.get(session['user_id'])
    api_keys = json.loads(user.api_keys)
    return jsonify({"api_keys": api_keys})

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)