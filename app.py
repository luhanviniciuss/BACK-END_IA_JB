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
            joined = "".join(words[-2:]).upper()
            # Pega MUITAS linhas para não perder ninguém (Aumentado para 200)
            cursor.execute("SELECT conteudo FROM documentos WHERE conteudo ILIKE %s LIMIT 200", (f"%SUBROTA: {joined}%",))
            rows = cursor.fetchall()
            
            seen_drivers = set()
            for r in rows:
                content = r['conteudo']
                match = re.search(r"Motorista:\s*([^|]+)", content)
                if match:
                    driver = match.group(1).strip()
                    if driver not in seen_drivers:
                        seen_drivers.add(driver)
                        all_results.append(content) # Adiciona a primeira linha que encontrar de cada motorista
        
        conn.close()
        return "\n\n".join(all_results)
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
        prompt = f"Você é o Especialista JB. Liste TODOS os motoristas diferentes que aparecem no contexto.\nCONTEXTO:\n{context}\n\nPERGUNTA: {question}"
        try:
            response = model.generate_content(prompt, stream=True)
            for chunk in response:
                if chunk.text: yield f"data: {json.dumps({'text': chunk.text})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e: yield f"data: {json.dumps({'text': str(e)})}\n\n"
    return Response(generate(), mimetype="text/event-stream")

if __name__ == "__main__":
    app.run()
