# Google OAuth Quick Setup Script for TalkEasy Voice Assistant (PowerShell)
# This script helps you configure Google OAuth credentials

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  TalkEasy - Google OAuth Setup" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# Check if .env exists
if (-not (Test-Path .env)) {
    Write-Host "Creating .env file from .env.example..." -ForegroundColor Yellow
    Copy-Item .env.example .env
    Write-Host "✓ Created .env file" -ForegroundColor Green
} else {
    Write-Host "✓ .env file already exists" -ForegroundColor Green
}

Write-Host ""
Write-Host "Please follow these steps to set up Google OAuth:" -ForegroundColor Yellow
Write-Host ""
Write-Host "1. Go to: https://console.cloud.google.com/apis/credentials"
Write-Host "2. Create a new OAuth 2.0 Client ID (Web application)"
Write-Host "3. Add this redirect URI: http://127.0.0.1:8000/auth/callback/google"
Write-Host "4. Copy your Client ID and Client Secret"
Write-Host ""

# Prompt for Google Client ID
$googleClientId = Read-Host "Enter your GOOGLE_CLIENT_ID"
if ($googleClientId) {
    $envContent = Get-Content .env -Raw
    if ($envContent -match "GOOGLE_CLIENT_ID=") {
        $envContent = $envContent -replace "GOOGLE_CLIENT_ID=.*", "GOOGLE_CLIENT_ID=$googleClientId"
    } else {
        $envContent += "`nGOOGLE_CLIENT_ID=$googleClientId"
    }
    Set-Content .env $envContent -NoNewline
    Write-Host "✓ Updated GOOGLE_CLIENT_ID" -ForegroundColor Green
}

# Prompt for Google Client Secret
$googleClientSecret = Read-Host "Enter your GOOGLE_CLIENT_SECRET"
if ($googleClientSecret) {
    $envContent = Get-Content .env -Raw
    if ($envContent -match "GOOGLE_CLIENT_SECRET=") {
        $envContent = $envContent -replace "GOOGLE_CLIENT_SECRET=.*", "GOOGLE_CLIENT_SECRET=$googleClientSecret"
    } else {
        $envContent += "`nGOOGLE_CLIENT_SECRET=$googleClientSecret"
    }
    Set-Content .env $envContent -NoNewline
    Write-Host "✓ Updated GOOGLE_CLIENT_SECRET" -ForegroundColor Green
}

# Generate JWT Secret if not set
$envContent = Get-Content .env -Raw
if ($envContent -match "JWT_SECRET=your_super_secret") {
    Write-Host ""
    Write-Host "Generating secure JWT_SECRET..." -ForegroundColor Yellow
    try {
        $jwtSecret = python -c "import secrets; print(secrets.token_urlsafe(32))"
        if ($jwtSecret) {
            $envContent = $envContent -replace "JWT_SECRET=.*", "JWT_SECRET=$jwtSecret"
            Set-Content .env $envContent -NoNewline
            Write-Host "✓ Generated JWT_SECRET" -ForegroundColor Green
        }
    } catch {
        Write-Host "⚠ Could not generate JWT_SECRET automatically" -ForegroundColor Yellow
        Write-Host "  Please update JWT_SECRET in .env manually" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  Setup Complete!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Your Google OAuth is configured. To test:" -ForegroundColor Yellow
Write-Host ""
Write-Host "1. Start the server: python main.py"
Write-Host "2. Open: http://127.0.0.1:8000/auth/login"
Write-Host "3. Click 'Sign in with Google'"
Write-Host ""
Write-Host "For detailed setup instructions, see: GOOGLE_OAUTH_SETUP.md" -ForegroundColor Cyan
Write-Host ""
