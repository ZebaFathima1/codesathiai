# ShopEasy API (sample repository)

A small Flask storefront API bundled with **CodeSathi AI** so you can explore a
real codebase without uploading anything.

## Layout

| Path | Purpose |
| --- | --- |
| `app.py` | Application factory and blueprint registration |
| `auth/login.py` | Login flow, JWT issue, logout |
| `api/users.py` | Registration and profile lookup |
| `api/orders.py` | Order creation and retrieval |
| `config/settings.py` | Environment configuration |
| `config/database.py` | SQLAlchemy engine and session setup |
| `models/user.py` | User model |
| `utils/security.py` | bcrypt password helpers |
| `utils/logger.py` | Logging helper |

## Try these questions in CodeSathi AI

- "Ee project lo login process ela work avutundi?"
- "How does login work?"
- "Where is the database configured?"
- "Explain the User model in simple Telugu."
- "What API routes exist?"

## Running the sample

```bash
pip install flask sqlalchemy pyjwt bcrypt
python app.py
```
