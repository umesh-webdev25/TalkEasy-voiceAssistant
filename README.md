# TalkEasy AI - Advanced Voice Assistant with Authentication

A modern, enterprise-ready AI voice assistant with full authentication system, beautiful UI, and advanced features built with FastAPI.

## 🚀 New Features

### 🎨 Beautiful Modern UI
- **Professional Landing Page**: Attractive home page with features, pricing, and contact sections
- **Responsive Design**: Mobile-first, fully responsive across all devices
- **Enhanced App Interface**: Improved voice assistant interface with user menu
- **Smooth Animations**: Engaging animations and transitions
- **Professional Branding**: Consistent TalkEasy AI branding throughout

### 🏢 Enterprise Features
- **User Plans**: Free, Pro, and Enterprise pricing tiers
- **Usage Tracking**: API usage monitoring and limits
- **Admin Dashboard**: Administrative controls and user management
- **Multi-tenancy**: Support for multiple users and organizations
- **Security**: Enhanced security measures and best practices

## 🎯 Core Features

- **Real-time Voice Interaction**: Stream audio input and receive real-time AI responses
- **Advanced Speech Recognition**: Powered by AssemblyAI for accurate transcription
- **Intelligent AI Responses**: Using Google's Gemini AI for natural conversations
- **High-quality Voice Synthesis**: Murf AI integration for natural-sounding speech
- **Web Search Integration**: Get real-time information from the web
- **Conversation History**: Persistent chat history with MongoDB
- **Multiple AI Personas**: Choose from different AI personality modes
- **WebSocket Streaming**: Real-time bidirectional communication

## 🛠 Tech Stack

### Backend
- **FastAPI**: Modern, fast web framework for APIs
- **Python 3.8+**: Core programming language
- **MongoDB**: Document database for data storage
- **JWT**: JSON Web Tokens for authentication
- **bcrypt**: Password hashing
- **WebSockets**: Real-time communication

### AI Services
- **AssemblyAI**: Speech-to-Text processing
- **Google Gemini**: Large Language Model
- **Murf AI**: Text-to-Speech synthesis
- **DuckDuckGo**: Web search integration

### Frontend
- **Modern HTML5**: Semantic markup
- **CSS3**: Advanced styling with animations
- **Vanilla JavaScript**: No framework dependencies
- **Font Awesome**: Professional icons
- **Responsive Design**: Mobile-first approach

## 📋 Prerequisites

- Python 3.8 or higher
- MongoDB (local or cloud instance)
- API Keys for:
  - AssemblyAI
  - Google Gemini
  - Murf AI

## 🚀 Quick Start

### 1. Clone and Install
```bash
git clone <repository-url>
cd 30days-murf-ai-agent
pip install -r requirements.txt
```

### 2. Environment Setup
Create a `.env` file:
```env
# AI Service API Keys
GEMINI_API_KEY=your_gemini_api_key
ASSEMBLYAI_API_KEY=your_assemblyai_api_key
MURF_API_KEY=your_murf_api_key
MURF_VOICE_ID=en-IN-aarav

# Database
MONGODB_URL=mongodb://localhost:27017

# Application Settings
AGENT_PERSONA=default
SECRET_KEY=your_secret_key_here
```

### 3. Run the Application
```bash
python main.py
```

### 4. Access the Application
- **Home Page**: http://127.0.0.1:8000
- **Login**: http://127.0.0.1:8000/login
- **Sign Up**: http://127.0.0.1:8000/signup
- **App**: http://127.0.0.1:8000/app

## 🔐 Authentication Flow

### Registration
1. Visit `/signup`
2. Fill in personal details
3. Password strength validation
4. Email format validation
5. Terms agreement
6. Account creation
7. Email verification (simulated)

### Login
1. Visit `/login`
2. Enter credentials
3. Password verification
4. JWT token generation
5. Redirect to app

### Demo Access
- Use the "Try Demo" button on the home page
- Access app without registration: `/app?demo=true`

## 🎨 UI Pages

### Home Page (`/`)
- Hero section with call-to-action
- Features showcase
- Pricing plans
- About section
- Contact form
- Professional footer

### Authentication Pages
Authentication functionality has been removed from this repository. The application runs without user accounts by default.

### App Interface (`/app`)
- Enhanced voice assistant
- User menu and profile
- Modern controls
- Real-time status indicators

## 📱 Responsive Design

- **Desktop**: Full-featured layout
- **Tablet**: Optimized for touch
- **Mobile**: Mobile-first design
- **All screen sizes**: Fully responsive

## 🔧 API Endpoints

### Authentication
Authentication endpoints have been removed from the codebase.

### Voice Chat
- `POST /agent/chat/{session_id}` - Process voice input
- `GET /agent/chat/{session_id}/history` - Get conversation history
- `DELETE /agent/chat/{session_id}/history` - Clear session history

### WebSocket
- `ws://localhost:8000/ws/audio-stream` - Real-time audio streaming

## 🏗 Project Structure

```
├── main.py                    # FastAPI application with auth routes
├── models/
│   ├── schemas.py            # Core API models
│   └── auth_schemas.py       # Authentication models
├── services/
│   ├── auth_service.py       # Authentication logic
│   ├── stt_service.py        # Speech-to-Text
│   ├── llm_service.py        # Language Model
│   ├── tts_service.py        # Text-to-Speech
│   └── database_service.py   # Database operations
├── templates/
│   ├── home.html             # Landing page
│   ├── index.html            # Voice assistant app
│   └── auth/
│       ├── login.html        # Login page
│       ├── signup.html       # Registration page
│       └── forgot-password.html
├── static/
│   ├── home.css             # Landing page styles
│   ├── auth.css             # Authentication styles
│   ├── style.css            # App styles
│   ├── home.js              # Landing page scripts
│   ├── auth.js              # Authentication scripts
│   └── app.js               # Voice assistant scripts
└── requirements.txt          # Dependencies with auth packages
```

## 🎯 Usage Examples

### Test Accounts
For demonstration:
- **Email**: `admin@talkeasy.ai`, **Password**: `admin123`  
- **Email**: `test@example.com`, **Password**: `Test123!`

### Voice Commands
- "What's the weather like?"
- "Tell me a joke"
- "Search for the latest news"
- "Help me with coding"

## 🚀 Deployment

### Development
```bash
python main.py
```

### Production
```bash
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### Docker
```dockerfile
FROM python:3.9
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
EXPOSE 8000
CMD ["python", "main.py"]
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

MIT License - see LICENSE file for details.

## 🆘 Support

- 📧 Email: talkeasyofficial100@gmail.com
- 📞 Phone: +91 7470480121
<<<<<<< HEAD
- 🌐 Website: [https://talkeasy.vercel.app](https://talkeasy-three.vercel.app/?session_id=session_nkh0hheuv_1761750089394)
  
=======
- 🌐 Website: talkeasy-three.vercel.app


>>>>>>> 17365c5 (final commmit)
---

**TalkEasy AI** - Experience the future of voice AI with enterprise-grade authentication and beautiful, responsive design! 🚀
