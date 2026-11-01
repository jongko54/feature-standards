"""A separate consumer project: imports the package; never copies authentication code."""

from typing import Annotated

from fastapi import Depends, Response
from feature_auth import create_app, current_user

app = create_app()


@app.get("/api/profile")
def profile(response: Response, user: Annotated[dict[str, str], Depends(current_user)]):
    response.headers["Cache-Control"] = "no-store"
    return {"consumer": "separate-project", "user": user}
