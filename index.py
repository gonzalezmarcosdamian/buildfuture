from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def home():
    return {"message": "Hello from BuildFuture on Vercel"}


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.6.1"}
