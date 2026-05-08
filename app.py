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
        
        # Pega as palavras (ex: for e 101)
        words = [w for w in clean_query.split() if len(w) >= 2 and w not in ["quem", "motorista", "rota"]]
        all_results = []
        
        if words:
            # 1. BUSCA SNIPER: Procura o código exato dentro do campo SUBROTA
            joined = "".join(words[-2:]).upper() # Ex: FOR101
            cursor.execute("SELECT conteudo FROM documentos WHERE conteudo ILIKE %s LIMIT 10", (f"%SUBROTA: {joined}%",))
            for r in cursor.fetchall(): all_results.append(r['conteudo'])

            # 2. SEGUNDA CHANCE: Se não achou com o código colado, tenta com espaço
            if not all_results and len(words) >= 2:
                with_space = " ".join(words[-2:]).upper() # Ex: FOR 101
                cursor.execute("SELECT conteudo FROM documentos WHERE conteudo ILIKE %s LIMIT 10", (f"%SUBROTA: {with_space}%",))
                for r in cursor.fetchall(): all_results.append(r['conteudo'])

            # 3. BUSCA AMPLA (Backup)
            if not all_results:
                where = " AND ".join(["conteudo ILIKE %s" for _ in words])
                params = [f"%{w}%" for w in words]
                cursor.execute(f"SELECT conteudo FROM documentos WHERE {where} LIMIT 20", params)
                for r in cursor.fetchall(): all_results.append(r['conteudo'])

        conn.close()
        return "\n\n".join(list(dict.fromkeys(all_results))[:20])
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
        prompt = f"Você é o Especialista JB. RESPONDA APENAS O NOME DO MOTORISTA OU O DADO SOLICITADO. RESPOSTA CURTA.\nCONTEXTO:\n{context}\n\nPERGUNTA: {question}"
        try:
            response = model.generate_content(prompt, stream=True)
            for chunk in response:
                if chunk.text: yield f"data: {json.dumps({'text': chunk.text})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e: yield f"data: {json.dumps({'text': str(e)})}\n\n"
    return Response(generate(), mimetype="text/event-stream")

if __name__ == "__main__":
    app.run()
