@echo off
echo Starting TicketVault Development Servers

:: 1. Check Frontend dependencies
if not exist "Frontend\node_modules\" (
    echo [Frontend] Installing Node dependencies...
    cd Frontend
    call npm install
    cd ..
) else (
    echo [Frontend] Node dependencies already installed.
)

:: 2. Check Backend Virtual Environment
if not exist "venv\" (
    echo [Backend] Creating Python virtual environment...
    python -m venv venv
    echo [Backend] Installing Python requirements...
    call venv\Scripts\activate
    pip install -r Backend\requirements.txt
) else (
    echo [Backend] Python virtual environment already exists.
)

:: 3. Start Backend in a new window
echo [Backend] Starting FastAPI server on port 8000...
start "TicketVault Backend" cmd /k "cd Backend && ..\venv\Scripts\activate && uvicorn main:app --reload --port 8000"

:: 4. Start Frontend in a new window
echo [Frontend] Starting Next.js server on port 3000...
start "TicketVault Frontend" cmd /k "cd Frontend && npm run dev"

echo Servers are launching in separate windows!
echo - Frontend: http://localhost:3000
echo - Backend:  http://localhost:8000
