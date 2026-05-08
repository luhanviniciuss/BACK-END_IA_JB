from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import os
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
        clean_query = query.lower().strip()
        stop_words = ["quem", "qual", "o", "a", "os", "as", "de", "do", "da", "em", "um", "no", "é", "motorista", "rota"]
        words = [w for w in clean_query.split() if w not in stop_words and len(w) >= 2]
        all_results = []
        if words:
            where = " AND ".join(["conteudo ILIKE %s" for _ in words])
            params = [f"%{w}%" for w in words]
            cursor.execute(f"SELECT conteudo FROM documentos WHERE {where} LIMIT 10", params)
            for r in cursor.fetchall(): all_results.append(r['conteudo'])
            if not all_results:
                for w in words:
                    if any(c.isdigit() for c in w) or len(w) >= 3:
                        cursor.execute("SELECT conteudo FROM documentos WHERE conteudo ILIKE %s LIMIT 5", (f"%{w}%",))
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
        VOCÊ É O ESPECIALISTA EM LOGÍSTICA DO GRUPO JB.
        
        INSTRUÇÃO CRÍTICA:
        1. Analise o CONTEXTO abaixo para responder à PERGUNTA.
        2. Seja flexível com códigos de rotas: Se o usuário perguntar por "FOR 101" e você encontrar "CAU101" (da Filial Fortaleza), entenda que é a mesma rota.
        3. Se encontrar o nome do Motorista ou Parceiro, responda apenas: "O motorista da rota [Nome da Rota] é [Nome do Motorista]."
        
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

@app.route("/api/login", methods=["POST", "OPTIONS"])
def login():
    if request.method == "OPTIONS": return jsonify({"status": "ok"}), 200
    data = request.json
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        pwd_hash = hashlib.sha256(data.get("password").encode()).hexdigest()
        cur.execute("SELECT id, username, role FROM usuarios WHERE username = %s AND password = %s", (data.get("username"), pwd_hash))
        user = cur.fetchone()
        conn.close()
        return jsonify({"status": "success", "user": user}) if user else (jsonify({"status": "error"}), 401)
    except Exception as e: return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run()
