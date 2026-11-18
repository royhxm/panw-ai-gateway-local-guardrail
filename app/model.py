import os, re, threading, time, gc, ctypes
from contextlib import asynccontextmanager
import torch
from fastapi import FastAPI, HTTPException
from transformers import AutoTokenizer, AutoModelForCausalLM

lock = threading.Lock()
slots = threading.BoundedSemaphore(4)


@asynccontextmanager
async def lifespan(app):
    global tokenizer, model
    torch.set_num_threads(int(os.environ.get("CPU_THREADS", "4")))
    tokenizer = AutoTokenizer.from_pretrained(
        os.environ.get("MODEL_PATH", "/cache/model"), local_files_only=True
    )
    model = (
        AutoModelForCausalLM.from_pretrained(
            os.environ.get("MODEL_PATH", "/cache/model"),
            local_files_only=True,
            dtype=torch.float32,
        )
        .eval()
        .cpu()
    )
    model = torch.quantization.quantize_dynamic(
        model, {torch.nn.Linear}, dtype=torch.qint8, inplace=True
    )
    gc.collect()
    ctypes.CDLL("libc.so.6").malloc_trim(0)
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "device": "cpu",
        "quantization": "dynamic-int8",
        "model": "Qwen/Qwen3Guard-Gen-0.6B",
    }


@app.post("/moderate")
def moderate(body: dict):
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(422, "messages required")
    text = tokenizer.apply_chat_template(messages, tokenize=False)
    inputs = tokenizer(text, return_tensors="pt")
    if inputs.input_ids.shape[1] > 4096:
        raise HTTPException(413, "context exceeds 4096 tokens")
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "model queue full")
    if not lock.acquire(timeout=60):
        slots.release()
        raise HTTPException(429, "model queue timeout")
    try:
        start = time.monotonic()
        with torch.inference_mode():
            ids = model.generate(**inputs, max_new_tokens=96, do_sample=False)
        output = tokenizer.decode(
            ids[0][inputs.input_ids.shape[1] :], skip_special_tokens=True
        )
        m = re.search(r"Safety:\s*(Safe|Unsafe|Controversial)", output)
        if not m:
            raise HTTPException(503, "unrecognized model verdict")
        cats = re.search(r"Categories:\s*([^\n]+)", output)
        return {
            "label": m[1],
            "categories": cats[1].strip() if cats else "Unknown",
            "seconds": round(time.monotonic() - start, 3),
        }
    finally:
        lock.release()
        slots.release()
