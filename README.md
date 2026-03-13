# My Service - Flask REST API

A Flask-based REST API service with user authentication and CRUD operations.

## Prerequisites

Before running this project, ensure you have the following installed:

- **Python 3.10** or higher
- **pip** (Python package installer)
- **virtualenv** (recommended for creating isolated Python environments)

### Installing Prerequisites

#### Python 3.10
- **macOS**: 
  ```bash
  brew install python@3.10
  ```
- **Ubuntu/Debian**:
  ```bash
  sudo apt update
  sudo apt install python3.10 python3.10-venv python3-pip
  ```
- **Windows**: Download from [python.org](https://www.python.org/downloads/)

#### virtualenv
```bash
pip install virtualenv
```

## Project Structure

```
my_service/
├── app/
│   ├── __init__.py              # Application factory
│   ├── config.py                # Environment configs
│   ├── database.py              # DB session management
│   ├── schemas.py               # Data validation schemas
│   ├── utils.py                 # Utility functions
│   ├── models/
│   │   ├── __init__.py          # Import db here
│   │   └── user.py              # User model
│   └── routes/
│       ├── __init__.py
│       ├── auth.py              # Login, register endpoints
│       └── users.py             # User CRUD endpoints
├── migrations/                  # Database migrations (future)
├── tests/                       # Test files (future)
├── requirements.txt             # Python dependencies
├── wsgi.py                      # WSGI entry point
└── README.md                    # This file
```

## Installation & Setup

### 1. Clone or Navigate to Project Directory

```bash
cd /path/to/my_service
```

### 2. Create Virtual Environment

```bash
python3.10 -m venv venv
```

### 3. Activate Virtual Environment

- **macOS/Linux**:
  ```bash
  source venv/bin/activate
  ```
- **Windows**:
  ```bash
  venv\Scripts\activate
  ```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Set Environment Variables (Optional)

Create a `.env` file in the project root (optional):

```bash
# .env
FLASK_ENV=development
SECRET_KEY=your-secret-key-here
JWT_SECRET_KEY=your-jwt-secret-key-here
DEV_DATABASE_URL=sqlite:///dev.db
```

If not set, the application will use default development values.

## Running the Application

### Development Mode

```bash
flask --app wsgi run --debug
```

Or:

```bash
python wsgi.py
```

The application will start at `http://127.0.0.1:5000`

### Production Mode

```bash
export FLASK_ENV=production
gunicorn -w 4 -b 0.0.0.0:8000 wsgi:app
```

Note: For production, you'll need to install gunicorn:
```bash
pip install gunicorn
```

## API Endpoints

### Authentication

- **POST** `/api/auth/register` - Register new user
  ```json
  {
    "username": "john_doe",
    "email": "john@example.com",
    "password": "password123"
  }
  ```

- **POST** `/api/auth/login` - Login user
  ```json
  {
    "email": "john@example.com",
    "password": "password123"
  }
  ```

### Users (Protected - Requires JWT Token)

- **GET** `/api/users/` - Get all users (paginated)
- **GET** `/api/users/me` - Get current user
- **GET** `/api/users/<user_id>` - Get specific user
- **PUT** `/api/users/<user_id>` - Update user
- **DELETE** `/api/users/<user_id>` - Delete user

### Authentication Header

For protected endpoints, include the JWT token in the Authorization header:

```
Authorization: Bearer <your_access_token>
```

## Testing the API

### Using curl

#### Register a user:
```bash
curl -X POST http://127.0.0.1:5000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","email":"test@example.com","password":"password123"}'
```

#### Login:
```bash
curl -X POST http://127.0.0.1:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"password123"}'
```

#### Get current user (with token):
```bash
curl -X GET http://127.0.0.1:5000/api/users/me \
  -H "Authorization: Bearer <your_access_token>"
```

## Database

By default, the application uses SQLite database (`dev.db`) in development mode. The database file will be created automatically when you first run the application.

## Troubleshooting

### Port Already in Use
If port 5000 is already in use, specify a different port:
```bash
flask --app wsgi run --port 5001
```

### Database Errors
Delete the database file and restart:
```bash
rm dev.db
python wsgi.py
```

### Module Not Found Errors
Ensure virtual environment is activated and dependencies are installed:
```bash
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
```

## Next Steps

- Add unit tests in the `tests/` directory
- Implement database migrations using Flask-Migrate
- Add API documentation using Flask-RESTX or Swagger
- Configure production database (PostgreSQL, MySQL)
- Set up proper logging and error handling
- Add rate limiting and CORS configuration

## License

This project is for educational purposes.
