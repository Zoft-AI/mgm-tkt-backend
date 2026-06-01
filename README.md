# MGM Ticket Backend

Standalone FastAPI backend extracted from `AI_crud` to serve the `mgm-tkt-frontend` exclusively.

## Overview

This project contains only the endpoints required by the MGM Ticket Frontend (Next.js). It excludes phone agents, campaigns, HITL, copilot, chat agent CRUD, Twilio, Ultravox, payment/subscription, and all other modules not used by the ticket frontend.

## Endpoints Served

### Auth (4 endpoints)
- `POST /public/auth/new` - Sync Supabase JWT with backend
- `POST /auth/signout` - Logout
- `POST /auth/sso/google` - Initiate Google SSO
- `POST /auth/sso/google/loading` - Exchange Google tokens

### Workspace (4 endpoints)
- `GET /public/workspace/get_workspace` - List workspaces
- `POST /public/workspace/get_agents` - List agents for workspace
- `POST /public/workspace/delete` - Delete workspace
- `GET /public/workspace/get_chat_agents` - List chat agents

### Requests / Inbox / Tickets (15 endpoints)
- `GET /requests/{agent_id}` - List requests
- `GET /requests/{agent_id}/{request_id}` - Get request detail
- `GET /requests/{agent_id}/raised-to-me` - Inbox
- `GET /requests/{agent_id}/raised-by-me` - Sent
- `GET /requests/{agent_id}/acted-by-me` - Acted
- `GET /requests/{agent_id}/admin/all` - Admin view
- `GET /requests/{agent_id}/dashboard` - Dashboard
- `POST /requests/{agent_id}` - Create request
- `POST /requests/{agent_id}/{request_id}/approve` - Approve
- `POST /requests/{agent_id}/{request_id}/reject` - Reject
- `POST /requests/{agent_id}/{request_id}/escalate` - Escalate
- `POST /requests/{agent_id}/{request_id}/revise-budget` - Revise budget
- `POST /requests/{agent_id}/upload-temp` - Temp file upload
- `POST /requests/{agent_id}/{request_id}/upload-attachment` - Upload attachment

### Products and Rules (5 endpoints)
- `GET /requests/{agent_id}/products` - List products
- `POST /requests/{agent_id}/products` - Create product
- `DELETE /requests/{agent_id}/products` - Bulk delete products
- `GET /requests/{agent_id}/products/categories` - List categories
- `GET /requests/{agent_id}/rules` - List rules

### Team / Members (2 endpoints)
- `GET /workspace/{workspace_id}/team` - List team members
- `GET /workspace/{workspace_id}/team/by-profile/{target_profile_id}` - Get member by profile

### Templates and URL Tools (2 endpoints)
- `GET /template/get_agents` - Bot templates
- `POST /url/extract/word` - URL word count extraction

## NOT Included (separate service)

The AI Chat endpoints (`POST /tester/chat`, `POST /tester/chat/embed`) are served by a separate service at `NEXT_PUBLIC_CHAT_URL` (default: `https://chat.zoft.ai:8000`) and are not part of this backend.

## Running

```bash
# Install dependencies
pip install -r requirements.txt

# Copy .env.example to .env and fill in values
cp .env.example .env

# Run development server
uvicorn app:app --host 127.0.0.1 --port 5000 --reload

# Run production (Docker)
docker build -t mgm-tkt-backend .
docker run -p 8000:8000 --env-file .env mgm-tkt-backend
```

## Architecture

```
mgm_tkt_backend/
├── app.py                  # FastAPI entrypoint + middleware + template route
├── config.py               # Environment config
├── requirements.txt        # Python dependencies
├── Dockerfile
├── .env.example
├── api/                    # Route handlers (thin layer)
│   ├── auth_endpoint.py
│   ├── workspace_endpoint.py
│   ├── request_endpoint.py
│   ├── member_endpoint.py
│   └── url_extraction_endpoint.py
├── services/               # Business logic
│   ├── auth.py
│   ├── workspace_service.py
│   ├── request_service.py
│   └── member_service.py
├── db/                     # Repository / data access
│   ├── workspace_repository.py
│   ├── request_repository.py
│   └── member_repository.py
├── models/                 # Pydantic request/response schemas
│   ├── workspace.py
│   ├── member.py
│   └── request.py
└── utils/                  # Shared utilities
    ├── database.py
    ├── sanitize.py
    ├── security.py
    ├── storage_operations.py
    ├── email_service.py
    ├── common.py
    └── global_error_handler.py
```

## Relationship to Original Codebase

- **Source**: Extracted from `AI_crud/` (full Zoft backend)
- **Frontend**: Serves `mgm-tkt-frontend/` (Next.js)
- **Chat Service**: Not included; frontend talks directly to `NEXT_PUBLIC_CHAT_URL`
