# TicketVault

## Overview

TicketVault is a full-stack concert ticket reselling platform designed to help users safely buy and sell event tickets. Sellers can create listings for tickets they can no longer use, while buyers can discover available listings by event and city, compare options, and complete purchases through a secure checkout flow.

The platform focuses on practical resale needs such as listing management, booking and order tracking, buyer detail capture during checkout, and reliable status handling across the ticket lifecycle. It also integrates authentication, payments, and backend validation to support trusted transactions between users.

The project is organized into:

- `Frontend/`: Next.js 14 + TypeScript web application
- `Backend/`: FastAPI service with booking, listing, and event APIs
- `Database/`: PostgreSQL schema and seed scripts for core entities

## Tech Stack

### Frontend

- Next.js 14
- React 18
- TypeScript
- Tailwind CSS
- Clerk authentication
- Supabase client SDK

### Backend

- Python + FastAPI
- Supabase
- Razorpay integration
- APScheduler (background jobs)

### Database

- PostgreSQL (Supabase-compatible schema)
- SQL migration scripts in `Database/schema.sql` and `Database/seed.sql`

## Prerequisites

Install the following before running locally:

- Node.js 18+ and npm
- Python 3.10+ and `pip`
- PostgreSQL or a Supabase project
- Clerk project credentials
- Razorpay credentials (for payment flows)

## Project Setup

### 1) Clone and open the project

```bash
git clone <your-repo-url>
cd TicketVault
```

### 2) Configure backend environment

Create `Backend/.env` from `Backend/.env.example` and fill in real values:

```env
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
CLERK_JWT_ISSUER=
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
CRON_SECRET=
```

### 3) Configure frontend environment

Create `Frontend/.env.local` from `Frontend/.env.example` and fill in values:

```env
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=
CLERK_SECRET_KEY=
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL=/
NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL=/
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
```

### 4) Set up database schema

Run the SQL files in this order:

1. `Database/schema.sql`
2. `Database/seed.sql`

## Run the Project

### Option A: Start both services with one command (Windows)

From the project root:

```bat
dev.bat
```

This script:

- installs frontend dependencies (if missing),
- creates backend virtual environment (if missing),
- installs backend dependencies,
- starts backend on `http://localhost:8000`,
- starts frontend on `http://localhost:3000`.

### Option B: Start services manually

#### Start backend

```bash
python -m venv venv
venv\Scripts\activate
pip install -r Backend/requirements.txt
cd Backend
uvicorn main:app --reload --port 8000
```

#### Start frontend (new terminal)

```bash
cd Frontend
npm install
npm run dev
```

Frontend: `http://localhost:3000`  
Backend: `http://localhost:8000`

## Available Frontend Scripts

From `Frontend/`:

- `npm run dev` - start development server
- `npm run build` - create production build
- `npm run start` - run production server
- `npm run lint` - run lint checks

## API and Health Check

Once backend is running, verify service health:

- `GET http://localhost:8000/health`

## Troubleshooting

- Ensure `Backend/.env` and `Frontend/.env.local` contain valid credentials.
- Confirm backend is running on port `8000` before opening frontend pages that call APIs.
- If authentication fails, verify Clerk keys and issuer values in both frontend and backend env files.
- If payment endpoints fail, verify Razorpay key configuration.
