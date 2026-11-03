# Feature Standards Python authentication

Session authentication for FastAPI with a reusable application factory and authentication dependency. The implementation follows the same behavioral contracts as the project's Go, Java, Rust, and browser clients.

```python
from typing import Annotated
from fastapi import Depends
from feature_auth import create_app, current_user

app = create_app()

@app.get("/private")
def private(user: Annotated[dict, Depends(current_user)]):
    return {"user": user}
```

Python 3.12 or later is required. Configuration is read when the application lifespan starts. In-memory mode supports one configured user and process-local sessions. PostgreSQL mode adds shared persistent sessions; the optional account lifecycle profile adds registration, email verification, and password reset.

For a loopback-only demo, explicitly set `AUTH_DEMO=true`, `AUTH_COOKIE_SECURE=false`, and `AUTH_ALLOWED_ORIGIN=http://127.0.0.1:5173`. Run Uvicorn with `--no-proxy-headers`. Demo credentials are `demo@example.com` / `correct-horse-battery-staple`; they are not production credentials.

Database migrations and seeding are explicit repository tools. Installing or starting this package does not create tables or users. Production HTTPS, proxy policy, secrets, mail delivery, and operational controls require deployment-specific configuration.

See the [source and integration guide](https://github.com/jongko54/feature-standards/tree/main/implementations/python-fastapi), [contracts](https://github.com/jongko54/feature-standards/tree/main/features/auth), and [security policy](https://github.com/jongko54/feature-standards/security/policy). Contract tests are not an independent security audit. MIT licensed.
