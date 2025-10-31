from fastapi import FastAPI


def create_app() -> FastAPI:
    """
    Build the FastAPI application with shared routes.
    Keeping this as a factory makes testing and extension easier.
    """
    app = FastAPI(title="X Automation System API", version="0.1.0")

    @app.get("/health", tags=["system"])
    async def health_check() -> dict[str, str]:
        """Basic liveness probe for infrastructure checks."""
        return {"status": "ok"}

    @app.get("/", tags=["system"])
    async def root() -> dict[str, str]:
        """Simple welcome route to verify the service boots."""
        return {"message": "X Automation System API ready"}

    return app


app = create_app()


if __name__ == "__main__":
    # Allows `python -m src.main` to run the app locally with uvicorn.
    import uvicorn

    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
