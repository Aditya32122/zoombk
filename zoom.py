from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
import httpx
import base64
from urllib.parse import urlencode, parse_qs
import secrets
from typing import Optional
import json

app = FastAPI(title="Zoom Recordings API")

# Add CORS middleware to allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration - Replace with your actual credentials
ZOOM_CONFIG = {
    "client_id": "VhQRheNdSwKLc79wBLGJeA", 
    "client_secret": "8WlYOsoHk6zNsociFvETLIHZ8bNR5bVj",
    "base_url": "https://api.zoom.us/v2",
    "redirect_uri": "http://127.0.0.1:8000/oauth/callback"  # Changed to match your server
}

# In-memory storage for demonstration (use database in production)
user_tokens = {}
oauth_states = {}

class ZoomOAuth:
    def __init__(self, config):
        self.config = config
        self.auth_url = "https://zoom.us/oauth/authorize"
        self.token_url = "https://zoom.us/oauth/token"
    
    def get_auth_url(self, state: str) -> str:
        """Generate OAuth authorization URL"""
        params = {
            "response_type": "code",
            "client_id": self.config["client_id"],
            "redirect_uri": self.config["redirect_uri"],
            "state": state,
            "scope": "recording:read user:read"  # Required: at least one scope must be specified
        }
        return f"{self.auth_url}?{urlencode(params)}"
    
    async def exchange_code_for_token(self, code: str) -> dict:
        """Exchange authorization code for access token"""
        auth_header = base64.b64encode(
            f"{self.config['client_id']}:{self.config['client_secret']}".encode()
        ).decode()
        
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config["redirect_uri"]
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(self.token_url, headers=headers, data=data)
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Token exchange failed: {response.text}"
                )
            
            return response.json()
    
    async def refresh_token(self, refresh_token: str) -> dict:
        """Refresh access token using refresh token"""
        auth_header = base64.b64encode(
            f"{self.config['client_id']}:{self.config['client_secret']}".encode()
        ).decode()
        
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(self.token_url, headers=headers, data=data)
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Token refresh failed: {response.text}"
                )
            
            return response.json()

# Initialize OAuth handler
zoom_oauth = ZoomOAuth(ZOOM_CONFIG)

class ZoomAPI:
    def __init__(self, config):
        self.config = config
    
    async def get_user_recordings(self, access_token: str, user_id: str = "me", 
                                 from_date: Optional[str] = None, 
                                 to_date: Optional[str] = None) -> dict:
        """Fetch user recordings from Zoom API"""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        params = {
            "page_size": 30,
            "next_page_token": ""
        }
        
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        
        url = f"{self.config['base_url']}/users/{user_id}/recordings"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            
            if response.status_code == 401:
                raise HTTPException(status_code=401, detail="Access token expired")
            elif response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code, 
                    detail=f"API request failed: {response.text}"
                )
            
            return response.json()
    
    async def get_user_info(self, access_token: str) -> dict:
        """Get user information"""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        url = f"{self.config['base_url']}/users/me"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code == 401:
                raise HTTPException(status_code=401, detail="Access token expired")
            elif response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code, 
                    detail=f"API request failed: {response.text}"
                )
            
            return response.json()

# Initialize Zoom API handler
zoom_api = ZoomAPI(ZOOM_CONFIG)

@app.get("/")
async def root():
    """Root endpoint with basic information"""
    return {
        "message": "Zoom Recordings API",
        "auth_endpoint": "/oauth/login",
        "recordings_endpoint": "/recordings"
    }

@app.get("/oauth/login")
async def oauth_login():
    """Initiate OAuth flow"""
    # Generate a random state for security
    state = secrets.token_urlsafe(32)
    oauth_states[state] = True
    
    auth_url = zoom_oauth.get_auth_url(state)
    
    return {
        "auth_url": auth_url,
        "message": "Visit the auth_url to authorize the application"
    }

@app.get("/oauth/login-simple")
async def oauth_login_simple():
    """Initiate OAuth flow without state (for testing)"""
    params = {
        "response_type": "code",
        "client_id": ZOOM_CONFIG["client_id"],
        "redirect_uri": ZOOM_CONFIG["redirect_uri"],
        # Removed scope parameter to match the requested URL
    }
    auth_url = f"https://zoom.us/oauth/authorize?{urlencode(params)}"
    
    return {
        "auth_url": auth_url,
        "message": "Visit the auth_url to authorize the application (simplified version)"
    }

@app.get("/oauth/callback")
async def oauth_callback(request: Request):
    """Handle OAuth callback"""
    query_params = dict(request.query_params)
    
    code = query_params.get("code")
    state = query_params.get("state")
    error = query_params.get("error")
    
    print(f"OAuth callback received - Code: {code}, State: {state}, Error: {error}")
    
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
    
    # Verify state to prevent CSRF attacks (if provided)
    if state:
        if state not in oauth_states:
            raise HTTPException(status_code=400, detail="Invalid state parameter")
        # Remove used state
        del oauth_states[state]
    else:
        print("Warning: No state parameter received in callback")
    
    try:
        # Exchange code for tokens
        token_data = await zoom_oauth.exchange_code_for_token(code)
        
        # Get user info
        user_info = await zoom_api.get_user_info(token_data["access_token"])
        user_id = user_info["id"]
        
        # Store tokens (in production, use secure database)
        user_tokens[user_id] = {
            "access_token": token_data["access_token"],
            "refresh_token": token_data["refresh_token"],
            "expires_in": token_data["expires_in"],
            "user_info": user_info
        }
        
        return {
            "message": "Authorization successful",
            "user_id": user_id,
            "user_email": user_info.get("email"),
            "access_token": token_data["access_token"]  # In production, don't return this directly
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth callback failed: {str(e)}")

@app.get("/recordings")
async def get_recordings(user_id: str, from_date: Optional[str] = None, 
                        to_date: Optional[str] = None):
    """Get user recordings"""
    if user_id not in user_tokens:
        raise HTTPException(
            status_code=401, 
            detail="User not authenticated. Please visit /oauth/login first."
        )
    
    token_info = user_tokens[user_id]
    access_token = token_info["access_token"]
    
    try:
        recordings = await zoom_api.get_user_recordings(
            access_token, user_id, from_date, to_date
        )
        return recordings
        
    except HTTPException as e:
        if e.status_code == 401:
            # Try to refresh token
            try:
                refresh_token = token_info["refresh_token"]
                new_token_data = await zoom_oauth.refresh_token(refresh_token)
                
                # Update stored tokens
                user_tokens[user_id].update({
                    "access_token": new_token_data["access_token"],
                    "refresh_token": new_token_data.get("refresh_token", refresh_token),
                    "expires_in": new_token_data["expires_in"]
                })
                
                # Retry the request with new token
                recordings = await zoom_api.get_user_recordings(
                    new_token_data["access_token"], user_id, from_date, to_date
                )
                return recordings
                
            except Exception as refresh_error:
                raise HTTPException(
                    status_code=401, 
                    detail="Token expired and refresh failed. Please re-authenticate."
                )
        else:
            raise e

@app.get("/user/{user_id}")
async def get_user_info(user_id: str):
    """Get user information"""
    if user_id not in user_tokens:
        raise HTTPException(
            status_code=401, 
            detail="User not authenticated. Please visit /oauth/login first."
        )
    
    token_info = user_tokens[user_id]
    return {
        "user_info": token_info["user_info"],
        "authenticated": True
    }

@app.delete("/oauth/logout/{user_id}")
async def logout(user_id: str):
    """Logout user (remove stored tokens)"""
    if user_id in user_tokens:
        del user_tokens[user_id]
        return {"message": "User logged out successfully"}
    else:
        raise HTTPException(status_code=404, detail="User not found")

@app.get("/oauth/status")
async def oauth_status():
    """Check OAuth status"""
    authenticated_users = list(user_tokens.keys())
    return {
        "authenticated_users": authenticated_users,
        "total_users": len(authenticated_users)
    }

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "zoom-recordings-api"}

@app.get("/debug/config")
async def debug_config():
    """Debug configuration endpoint"""
    return {
        "client_id": ZOOM_CONFIG["client_id"],
        "redirect_uri": ZOOM_CONFIG["redirect_uri"],
        "base_url": ZOOM_CONFIG["base_url"],
        "auth_url": "https://zoom.us/oauth/authorize",
        "token_url": "https://zoom.us/oauth/token"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)