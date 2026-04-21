#!/bin/bash

# Google OAuth Quick Setup Script for TalkEasy Voice Assistant
# This script helps you configure Google OAuth credentials

echo "========================================="
echo "  TalkEasy - Google OAuth Setup"
echo "========================================="
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "Creating .env file from .env.example..."
    cp .env.example .env
    echo "✓ Created .env file"
else
    echo "✓ .env file already exists"
fi

echo ""
echo "Please follow these steps to set up Google OAuth:"
echo ""
echo "1. Go to: https://console.cloud.google.com/apis/credentials"
echo "2. Create a new OAuth 2.0 Client ID (Web application)"
echo "3. Add this redirect URI: http://127.0.0.1:8000/auth/callback/google"
echo "4. Copy your Client ID and Client Secret"
echo ""

# Prompt for Google Client ID
read -p "Enter your GOOGLE_CLIENT_ID: " google_client_id
if [ ! -z "$google_client_id" ]; then
    # Update .env file
    if grep -q "GOOGLE_CLIENT_ID=" .env; then
        sed -i.bak "s|GOOGLE_CLIENT_ID=.*|GOOGLE_CLIENT_ID=$google_client_id|" .env
    else
        echo "GOOGLE_CLIENT_ID=$google_client_id" >> .env
    fi
    echo "✓ Updated GOOGLE_CLIENT_ID"
fi

# Prompt for Google Client Secret
read -p "Enter your GOOGLE_CLIENT_SECRET: " google_client_secret
if [ ! -z "$google_client_secret" ]; then
    if grep -q "GOOGLE_CLIENT_SECRET=" .env; then
        sed -i.bak "s|GOOGLE_CLIENT_SECRET=.*|GOOGLE_CLIENT_SECRET=$google_client_secret|" .env
    else
        echo "GOOGLE_CLIENT_SECRET=$google_client_secret" >> .env
    fi
    echo "✓ Updated GOOGLE_CLIENT_SECRET"
fi

# Generate JWT Secret if not set
if ! grep -q "JWT_SECRET=your_super_secret" .env 2>/dev/null; then
    echo ""
    echo "Generating secure JWT_SECRET..."
    jwt_secret=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || openssl rand -base64 32)
    if [ ! -z "$jwt_secret" ]; then
        if grep -q "JWT_SECRET=" .env; then
            sed -i.bak "s|JWT_SECRET=.*|JWT_SECRET=$jwt_secret|" .env
        else
            echo "JWT_SECRET=$jwt_secret" >> .env
        fi
        echo "✓ Generated JWT_SECRET"
    fi
fi

echo ""
echo "========================================="
echo "  Setup Complete!"
echo "========================================="
echo ""
echo "Your Google OAuth is configured. To test:"
echo ""
echo "1. Start the server: python main.py"
echo "2. Open: http://127.0.0.1:8000/auth/login"
echo "3. Click 'Sign in with Google'"
echo ""
echo "For detailed setup instructions, see: GOOGLE_OAUTH_SETUP.md"
echo ""
