from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import os
import re
import hashlib
import google.generativeai as genai

app = Flask(__name__)
app.secret_key = "jb_secret_key_intelligence"
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

@app.after_request
def after_request(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
    return response

def get_db_connection():
    db_url = os.getenv("DATABASE_URL")
    if "supabase.com" in db_url and "sslmode" not in db_url:
        db_url += "&sslmode=require" if "?" in db_url else "?sslmode=require"
    return psycopg2.connect(db_url)

def get_context(query):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        clean_query = re.sub(r"[^\w\s]", " ", query.lower()).strip()
        stop_words = ["quem", "qual", "o", "a", "os", "as", "de", "do", "da", "em", "um", "no", "é", "motorista", "rota", "subrota"]
        words = [w for w in clean_query.split() if w not in stop_words and len(w) >= 2]
        all_results = []
        
        if words:
            # 1. Busca por termos combinados (AND) - LIMITE AUMENTADO PARA 50
            where = " AND ".join(["conteudo ILIKE %s" for _ in words])
            params = [f"%{w}%" for w in words]
            cursor.execute(f"SELECT conteudo FROM documentos WHERE {where} LIMIT 50", params)
            for r in cursor.fetchall(): all_results.append(r['conteudo'])

            # 2. Busca pelo código "grudado" se houver espaço
            if len(words) >= 2:
                joined = "".join(words[-2:]) # Pega os dois últimos termos (ex: for e 101)
                cursor.execute("SELECT conteudo FROM documentos WHERE conteudo ILIKE %s LIMIT 20", (f"%{joined}%",))
                for r in cursor.fetchall(): all_results.append(r['conteudo'])
        
        conn.close()
        return "\n\n".join(list(dict.fromkeys(all_results))[:30]) # Entrega mais contexto para a IA decidir
    except: return ""

@app.route("/api/ask", methods=["POST", "OPTIONS"])
def ask():
    if request.method == "OPTIONS": return jsonify({"status": "ok"}), 200
    data = request.json
    question = data.get("question")
    context = get_context(question)
    def generate():
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model = genai.GenerativeModel("gemini-flash-latest")
        prompt = f"""
        Você é o Especialista JB. 
        Procure no CONTEXTO pela rota exata pedida.
        Diferencie bem códigos parecidos (Ex: FOR101 é diferente de CAU101).
        
        CONTEXTO:
        {context}

        PERGUNTA: {question}
        """
        try:
            response = model.generate_content(prompt, stream=True)
            for chunk in response:
                if chunk.text: yield f"data: {json.dumps({'text': chunk.text})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e: yield f"data: {json.dumps({'text': str(e)})}\n\n"
    return Response(generate(), mimetype="text/event-stream")

if __name__ == "__main__":
    app.run()
