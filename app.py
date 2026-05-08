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
        
        # 1. Tenta a busca pelo termo GRUDADO (Ex: FOR101)
        term_joined = clean_query.replace(" ", "")
        all_results = []
        
        cursor.execute("SELECT conteudo FROM documentos WHERE conteudo ILIKE %s LIMIT 10", (f"%{term_joined}%",))
        for r in cursor.fetchall(): all_results.append(r['conteudo'])

        # 2. Se não achar nada grudado, tenta a busca AND
        if not all_results:
            stop_words = ["quem", "qual", "o", "a", "os", "as", "de", "do", "da", "em", "um", "no", "é", "motorista", "rota"]
            words = [w for w in clean_query.split() if w not in stop_words and len(w) >= 2]
            if words:
                where = " AND ".join(["conteudo ILIKE %s" for _ in words])
                params = [f"%{w}%" for w in words]
                cursor.execute(f"SELECT conteudo FROM documentos WHERE {where} LIMIT 10", params)
                for r in cursor.fetchall(): all_results.append(r['conteudo'])

        conn.close()
        return "\n\n".join(list(dict.fromkeys(all_results))[:15])
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
        
        REGRAS DE OURO:
        1. Identifique o código da ROTA na pergunta.
        2. Procure no CONTEXTO pela linha onde 'SUBROTA:' seja EXATAMENTE igual ao código (Ex: FOR101).
        3. Se a pergunta for sobre FOR101, ignore resultados de CAU101.
        4. Responda apenas: "O motorista da rota [Código] é [Nome]."
        
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
