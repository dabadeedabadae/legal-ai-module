import os
from dotenv import load_dotenv
load_dotenv()

PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
GROQ_MODEL = "llama-3.3-70b-versatile"

def chat(prompt: str) -> str:
    """Универсальная функция — работает с Groq или Ollama"""
    
    if PROVIDER == "groq":
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        return response.choices[0].message.content
    
    else:  # ollama
        import ollama
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1}
        )
        return response["message"]["content"]
