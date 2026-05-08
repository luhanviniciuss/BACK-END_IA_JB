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
        words = [w for w in clean_query.split() if len(w) >= 2 and w not in ["quem", "motorista", "rota"]]
        all_results = []
        
        if words:
            # 1. Busca específica por SUBROTA (Ex: FOR101)
            joined = "".join(words[-2:]).upper()
            cursor.execute("SELECT conteudo FROM documentos WHERE conteudo ILIKE %s LIMIT 15", (f"%SUBROTA: {joined}%",))
            for r in cursor.fetchall(): all_results.append(r['conteudo'])

            # 2. Busca ampla se a primeira falhar
            if not all_results:
                where = " AND ".join(["conteudo ILIKE %s" for _ in words])
                cursor.execute(f"SELECT conteudo FROM documentos WHERE {where} LIMIT 20", [f"%{w}%" for w in words])
                for r in cursor.fetchall(): all_results.append(r['conteudo'])

        conn.close()
        res = "\n\n".join(list(dict.fromkeys(all_results))[:20])
        return res if res else "NENHUM DADO ENCONTRADO NO BANCO."
    except Exception as e:
        return f"ERRO DE CONEXÃO COM BANCO: {str(e)}"

@app.route("/api/ask", methods=["POST", "OPTIONS"])
def ask():
    if request.method == "OPTIONS": return jsonify({"status": "ok"}), 200
    data = request.json
    question = data.get("question")
    context = get_context(question)
    def generate():
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model = genai.GenerativeModel("gemini-flash-latest")
        prompt = f"VOCÊ É O ESPECIALISTA JB.\nCONTEXTO:\n{context}\n\nPERGUNTA: {question}\n\nSe o contexto disser 'NENHUM DADO ENCONTRADO', diga que não consta. Caso contrário, extraia o motorista."
        try:
            response = model.generate_content(prompt, stream=True)
            for chunk in response:
                if chunk.text: yield f"data: {json.dumps({'text': chunk.text})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e: yield f"data: {json.dumps({'text': str(e)})}\n\n"
    return Response(generate(), mimetype="text/event-stream")

if __name__ == "__main__":
    app.run()
