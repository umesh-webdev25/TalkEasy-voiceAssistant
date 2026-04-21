from motor.motor_asyncio import AsyncIOMotorClient
import certifi
from typing import List, Dict, Optional
from datetime import datetime
import logging
import os

logger = logging.getLogger(__name__)


class DatabaseService:
    def __init__(self, mongodb_url: str = None):
        self.mongodb_url = mongodb_url or os.getenv("MONGODB_URL")
        self.db_name = os.getenv("MONGODB_DB_NAME", "voiceAssistance")
        self.ssl_allow_invalid = os.getenv("MONGODB_SSL_ALLOW_INVALID_CERTIFICATES", "false").lower() == "true"
        self.client = None
        self.db = None
        self.in_memory_store = {}
        self.user_sessions = {}  # Track user sessions for better organization
    
    async def connect(self) -> bool:
        try:
            logger.info(f"🔗 Connecting to MongoDB: {self.mongodb_url[:50]}...")
            motor_kwargs = {
                "serverSelectionTimeoutMS": 10000,
                "connectTimeoutMS": 10000,
                "socketTimeoutMS": 20000,
                "maxPoolSize": 10,
            }
            # If connecting to MongoDB Atlas (mongodb+srv or mongodb.net hostnames),
            # ensure we explicitly enable TLS and provide a CA bundle from certifi.
            try:
                if self.mongodb_url and (self.mongodb_url.startswith("mongodb+srv://") or "mongodb.net" in self.mongodb_url):
                    motor_kwargs["tls"] = True
                    motor_kwargs["tlsCAFile"] = certifi.where()
                    # increase selection timeout a bit for DNS SRV lookups
                    motor_kwargs["serverSelectionTimeoutMS"] = 20000
            except Exception:
                # Fall back to defaults if certifi is unavailable for any reason
                pass
            # Only add SSL bypass if requested (for Atlas troubleshooting)
            if self.ssl_allow_invalid:
                motor_kwargs["tlsAllowInvalidCertificates"] = True
                motor_kwargs["tlsAllowInvalidHostnames"] = True
            self.client = AsyncIOMotorClient(self.mongodb_url, **motor_kwargs)
            # Select database from env (explicit is better than inferring from URL)
            db_name = self.db_name
            self.db = self.client[db_name]
            # Test the connection
            await self.client.admin.command('ping')
            logger.info("✅ MongoDB ping successful")
            # Create the database by inserting a test document (MongoDB creates DB on first write)
            await self._ensure_database_exists()
            # Create collections and indexes
            await self._initialize_collections()
            logger.info("✅ Connected to MongoDB Atlas successfully")
            logger.info(f"📊 Using database: {db_name}")
            logger.info(f"🌐 Connected to: {self.mongodb_url.split('@')[1].split('/')[0] if '@' in self.mongodb_url else 'localhost'}")
            return True
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            logger.info("💾 Using in-memory storage as fallback")
            self.client = None
            self.db = None
            return False
    
    async def _ensure_database_exists(self):
        """Ensure database exists by creating a test document"""
        try:
            # Insert a system document to create the database
            system_doc = {
                "_id": "system_init",
                "created_at": datetime.now(),
                "app_name": "TalkEasy Voice Assistant",
                "version": "1.0.0"
            }
            
            await self.db.system_info.replace_one(
                {"_id": "system_init"}, 
                system_doc, 
                upsert=True
            )
            
            logger.info("✅ Database 'voiceAssistance' created/verified successfully")
            
        except Exception as e:
            logger.warning(f"⚠️ Could not create database: {e}")

    async def _initialize_collections(self):
        """Initialize required collections and indexes"""
        try:
            # List existing collections
            collections = await self.db.list_collection_names()
            logger.info(f"📋 Existing collections: {collections}")
            
            # Create indexes for better performance
            await self.db.chat_sessions.create_index("session_id", unique=True)
            await self.db.chat_sessions.create_index("last_activity")
            await self.db.users.create_index("email", unique=True)
            # Create revoked_tokens collection and TTL index on expires_at so tokens auto-expire
            try:
                await self.db.revoked_tokens.create_index("token", unique=True)
                # expireAfterSeconds=0 makes MongoDB remove documents once 'expires_at' time is reached
                await self.db.revoked_tokens.create_index("expires_at", expireAfterSeconds=0)
            except Exception as e:
                logger.warning(f"⚠️ Could not create revoked_tokens indexes: {e}")
            
            # Create a sample user for testing (if users collection is empty)
            user_count = await self.db.users.count_documents({})
            if user_count == 0:
                sample_user = {
                    "id": "system_test_user",
                    "email": "test@example.com",
                    "name": "Test User",
                    "created_at": datetime.now(),
                    "is_system": True
                }
                await self.db.users.insert_one(sample_user)
                logger.info("👤 Created sample test user")
            
            # Verify collections were created
            final_collections = await self.db.list_collection_names()
            logger.info(f"📋 Final collections: {final_collections}")
            logger.info("✅ Database collections and indexes initialized successfully")
            
        except Exception as e:
            logger.warning(f"⚠️ Could not create indexes: {e}")
    
    def is_connected(self) -> bool:
        """Check if database is connected"""
        return self.db is not None
    
    async def test_connection(self) -> bool:
        """Test database connection"""
        if self.db is not None:
            try:
                await self.client.admin.command('ping')
                return True
            except Exception as e:
                logger.error(f"Database connection test failed: {e}")
                return False
        return False
    
    async def get_all_chat_histories(self) -> List[Dict]:
        """Get all chat histories across sessions (latest first)"""
        if self.db is not None:
            try:
                cursor = self.db.chat_sessions.find({}, {"_id": 0})
                histories = await cursor.to_list(length=None)
                return histories[::-1]  # latest at top
            except Exception as e:
                logger.error(f"Failed to get all chat histories: {str(e)}")
                # fallback to in-memory - normalize structure
                histories = []
                for sid, sess in reversed(list(self.in_memory_store.items())):
                    if isinstance(sess, dict):
                        messages = sess.get("messages", [])
                        histories.append({
                            "session_id": sid,
                            "messages": messages,
                            "created_at": sess.get("created_at"),
                            "last_updated": sess.get("last_updated"),
                            "message_count": sess.get("message_count", len(messages)),
                            "user_id": sess.get("user_id")
                        })
                    else:
                        # old shape: stored as raw message list
                        msgs = sess or []
                        histories.append({
                            "session_id": sid,
                            "messages": msgs,
                            "created_at": None,
                            "last_updated": None,
                            "message_count": len(msgs),
                            "user_id": None
                        })
                return histories
        else:
            # fallback if DB not connected - normalize structure
            histories = []
            for sid, sess in reversed(list(self.in_memory_store.items())):
                if isinstance(sess, dict):
                    messages = sess.get("messages", [])
                    histories.append({
                        "session_id": sid,
                        "messages": messages,
                        "created_at": sess.get("created_at"),
                        "last_updated": sess.get("last_updated"),
                        "message_count": sess.get("message_count", len(messages)),
                        "user_id": sess.get("user_id")
                    })
                else:
                    msgs = sess or []
                    histories.append({
                        "session_id": sid,
                        "messages": msgs,
                        "created_at": None,
                        "last_updated": None,
                        "message_count": len(msgs),
                        "user_id": None
                    })
            return histories

    
    async def get_chat_history(self, session_id: str) -> List[Dict]:
        """Get chat history for a session"""
        if self.db is not None:
            try:
                chat_history = await self.db.chat_sessions.find_one({"session_id": session_id})
                if chat_history and "messages" in chat_history:
                    return chat_history["messages"]
                return []
            except Exception as e:
                logger.error(f"Failed to get chat history from MongoDB: {str(e)}")
                return self.in_memory_store.get(session_id, [])
        else:
            return self.in_memory_store.get(session_id, [])
    
    async def add_message_to_history(self, session_id: str, role: str, content: str, user_id: Optional[str] = None) -> bool:
        """Add a message to chat history with improved error handling"""
        if not session_id or not role or not content:
            logger.error(f"Invalid parameters for add_message_to_history: session_id={session_id}, role={role}, content_length={len(content) if content else 0}")
            return False
            
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now()
        }
        
        # Track user sessions for analytics
        if session_id not in self.user_sessions:
            self.user_sessions[session_id] = {
                "created_at": datetime.now(),
                "message_count": 0,
                "last_activity": datetime.now()
            }
        
        self.user_sessions[session_id]["message_count"] += 1
        self.user_sessions[session_id]["last_activity"] = datetime.now()
        
        if self.db is not None:
            try:
                # Update chat session with user session metadata
                session_metadata = {
                    "session_id": session_id,
                    "created_at": self.user_sessions[session_id]["created_at"],
                    "message_count": self.user_sessions[session_id]["message_count"],
                    "last_activity": self.user_sessions[session_id]["last_activity"]
                }
                # If a user_id is provided, include it in session metadata so sessions can be attributed
                if user_id:
                    session_metadata["user_id"] = user_id

                result = await self.db.chat_sessions.update_one(
                    {"session_id": session_id},
                    {
                        "$push": {"messages": message},
                        "$set": {
                            "last_updated": datetime.now(),
                            **session_metadata
                        }
                    },
                    upsert=True
                )
                
                if result.matched_count > 0 or result.upserted_id:
                    logger.info(f"✅ Message saved to MongoDB for session {session_id}: {role} - {content[:50]}...")
                else:
                    logger.warning(f"⚠️ MongoDB update didn't match any documents for session {session_id}")
                    
                return True
            except Exception as e:
                logger.error(f"❌ Failed to save message to MongoDB: {str(e)}")
                # Fallback to in-memory storage; attach metadata at session level
                if session_id not in self.in_memory_store:
                    self.in_memory_store[session_id] = {
                        "messages": [],
                        "created_at": self.user_sessions[session_id]["created_at"],
                        "message_count": self.user_sessions[session_id]["message_count"],
                        "last_updated": datetime.now()
                    }
                self.in_memory_store[session_id]["messages"].append(message)
                if user_id:
                    self.in_memory_store[session_id]["user_id"] = user_id
                logger.info(f"💾 Message saved to in-memory storage for session {session_id}: {role} - {content[:50]}...")
                return True
        else:
            # In-memory storage when MongoDB is not available; store session-level metadata
            if session_id not in self.in_memory_store:
                self.in_memory_store[session_id] = {
                    "messages": [],
                    "created_at": self.user_sessions[session_id]["created_at"],
                    "message_count": self.user_sessions[session_id]["message_count"],
                    "last_updated": datetime.now()
                }
            self.in_memory_store[session_id]["messages"].append(message)
            if user_id:
                self.in_memory_store[session_id]["user_id"] = user_id
            logger.info(f"💾 Message saved to in-memory storage for session {session_id}: {role} - {content[:50]}...")
            return True
    
    async def get_user_sessions(self, limit: int = 50) -> List[Dict]:
        """Get recent user sessions for analytics"""
        if self.db is not None:
            try:
                sessions = await self.db.chat_sessions.find(
                    {},
                    {"session_id": 1, "created_at": 1, "message_count": 1, "last_activity": 1}
                ).sort("last_activity", -1).limit(limit).to_list(length=limit)
                return sessions
            except Exception as e:
                logger.error(f"Failed to get user sessions from MongoDB: {str(e)}")
                return []
        else:
            # Return in-memory session data
            return list(self.user_sessions.items())[:limit]
    
    async def clear_session_history(self, session_id: str) -> bool:
            """Delete an entire session including history and metadata"""
            if self.db is not None:
                try:
                    result = await self.db.chat_sessions.delete_one({"session_id": session_id})
                    logger.info(f"Deleted entire session {session_id} from MongoDB")
                    # Also remove from in-memory cache
                    if session_id in self.in_memory_store:
                        del self.in_memory_store[session_id]
                    if session_id in self.user_sessions:
                        del self.user_sessions[session_id]
                    return result.deleted_count > 0
                except Exception as e:
                    logger.error(f"Failed to delete session {session_id} from MongoDB: {str(e)}")
                    # Cleanup in-memory as fallback
                    if session_id in self.in_memory_store:
                        del self.in_memory_store[session_id]
                    if session_id in self.user_sessions:
                        del self.user_sessions[session_id]
                    return True
            else:
                # Only in-memory deletion
                if session_id in self.in_memory_store:
                    del self.in_memory_store[session_id]
                if session_id in self.user_sessions:
                    del self.user_sessions[session_id]
                logger.info(f"Deleted entire session {session_id} from in-memory store")
                return True

    async def get_session_stats(self, session_id: str) -> Dict:
        """Get statistics for a specific session"""
        if self.db is not None:
            try:
                session = await self.db.chat_sessions.find_one({"session_id": session_id})
                if session:
                    return {
                        "session_id": session_id,
                        "message_count": len(session.get("messages", [])),
                        "created_at": session.get("created_at"),
                        "last_activity": session.get("last_activity"),
                        "total_user_messages": len([m for m in session.get("messages", []) if m["role"] == "user"]),
                        "total_assistant_messages": len([m for m in session.get("messages", []) if m["role"] == "assistant"])
                    }
                return {}
            except Exception as e:
                logger.error(f"Failed to get session stats from MongoDB: {str(e)}")
                return {}
        else:
            messages = self.in_memory_store.get(session_id, [])
            session_info = self.user_sessions.get(session_id, {})
            return {
                "session_id": session_id,
                "message_count": len(messages),
                "created_at": session_info.get("created_at"),
                "last_activity": session_info.get("last_activity"),
                "total_user_messages": len([m for m in messages if m["role"] == "user"]),
                "total_assistant_messages": len([m for m in messages if m["role"] == "assistant"])
            }
    
    # User management methods for authentication
    async def create_user(self, user_data: Dict) -> bool:
        """Create a new user in the database"""
        if self.db is not None:
            try:
                result = await self.db.users.insert_one(user_data)
                logger.info(f"✅ User created with ID: {result.inserted_id}")
                return True
            except Exception as e:
                logger.error(f"❌ Failed to create user: {str(e)}")
                return False
        return False
    
    async def get_user_by_email(self, email: str) -> Optional[Dict]:
        """Get user by email from database"""
        if self.db is not None:
            try:
                user = await self.db.users.find_one({"email": email}, {"_id": 0})
                return user
            except Exception as e:
                logger.error(f"❌ Failed to get user by email: {str(e)}")
                return None
        return None
    
    async def update_user_last_login(self, user_id: str) -> bool:
        """Update user's last login timestamp"""
        if self.db is not None:
            try:
                result = await self.db.users.update_one(
                    {"id": user_id},
                    {"$set": {"last_login": datetime.now()}}
                )
                return result.modified_count > 0
            except Exception as e:
                logger.error(f"❌ Failed to update last login: {str(e)}")
                return False
        return False
    
    async def user_exists(self, email: str) -> bool:
        """Check if user exists by email"""
        if self.db is not None:
            try:
                count = await self.db.users.count_documents({"email": email})
                return count > 0
            except Exception as e:
                logger.error(f"❌ Failed to check user existence: {str(e)}")
                return False
        return False

    # Revoked token support
    async def add_revoked_token(self, token: str, expires_ts: Optional[int] = None) -> bool:
        """Persist a revoked token to the database (or in-memory fallback).

        expires_ts (optional): epoch seconds when the token expires; used to set a TTL index field.
        """
        if not token:
            return False

        if self.db is not None:
            try:
                doc = {
                    "token": token,
                    "revoked_at": datetime.now()
                }
                if expires_ts:
                    try:
                        doc["expires_at"] = datetime.fromtimestamp(int(expires_ts))
                    except Exception:
                        doc["expires_at"] = None

                await self.db.revoked_tokens.replace_one({"token": token}, doc, upsert=True)
                logger.info("✅ Revoked token persisted to DB")
                return True
            except Exception as e:
                logger.error(f"❌ Failed to persist revoked token to DB: {e}")
                # Fall through to in-memory fallback

        # In-memory fallback
        if "revoked_tokens" not in self.in_memory_store:
            self.in_memory_store["revoked_tokens"] = []
        try:
            self.in_memory_store["revoked_tokens"].append({"token": token, "expires_at": expires_ts})
            logger.info("💾 Revoked token saved to in-memory store")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to store revoked token in-memory: {e}")
            return False

    async def is_token_revoked(self, token: str) -> bool:
        """Check whether a token is present in the revoked list (DB or in-memory)."""
        if not token:
            return False
        if self.db is not None:
            try:
                found = await self.db.revoked_tokens.find_one({"token": token})
                return found is not None
            except Exception as e:
                logger.warning(f"Could not query revoked_tokens collection: {e}")
                # fall back to in-memory

        for rec in self.in_memory_store.get("revoked_tokens", []):
            try:
                if rec.get("token") == token:
                    return True
            except Exception:
                continue
        return False
    
    async def close(self):
        if self.client:
            self.client.close()
            logger.info("Database connection closed")

    async def test_database_operations(self):
        """Test database operations to ensure everything works"""
        try:
            logger.info("🧪 Testing database operations...")
            # Test 1: Insert a test document
            test_doc = {
                "test_id": "database_test",
                "timestamp": datetime.now(),
                "message": "Database connection test successful",
            }
            result = await self.db.test_collection.insert_one(test_doc)
            logger.info(f"✅ Test document inserted with ID: {result.inserted_id}")
            # Test 2: Read the document back
            retrieved = await self.db.test_collection.find_one({"test_id": "database_test"})
            if retrieved:
                logger.info("✅ Test document retrieved successfully")
            # Test 3: List all databases
            db_list = await self.client.list_database_names()
            logger.info(f"📊 Available databases: {db_list}")
            # Test 4: List collections in our database
            collections = await self.db.list_collection_names()
            logger.info(f"📋 Collections in {self.db_name}: {collections}")
            # Clean up test document
            await self.db.test_collection.delete_one({"test_id": "database_test"})
            logger.info("🧹 Test document cleaned up")
            logger.info("🎉 All database tests passed!")
            return True
        except Exception as e:
            logger.error(f"❌ Database test failed: {e}")
            return False