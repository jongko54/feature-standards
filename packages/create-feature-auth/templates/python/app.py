from typing import Annotated

from fastapi import Depends, Response
from feature_auth import create_app, current_user

app = create_app()


@app.get("/api/profile")
def profile(response: Response, user: Annotated[dict[str, str], Depends(current_user)]):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return {"user": user}
