"""Test script to debug user creation issues"""
import asyncio
import sys
import logging
from services.auth_service import AuthService

# Enable logging to see email sending status
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(name)s - %(message)s')

async def test_user_creation():
    """Test creating a user"""
    auth = AuthService()
    
    try:
        print("🔍 Testing user creation...")
        user = await auth.create_user(
            email="newuser2@gmail.com",
            first_name="New",
            last_name="User",
            password="testpassword123"
        )
        print(f"✅ User created successfully: {user['email']}")
        print(f"   User ID: {user['id']}")
        print(f"   Name: {user['first_name']} {user['last_name']}")
        return True
    except ValueError as ve:
        print(f"❌ ValueError: {ve}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_user_creation())
    sys.exit(0 if success else 1)
