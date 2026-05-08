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
        
        # Pega todas as palavras com 2 ou mais letras
        words = [w for w in clean_query.split() if len(w) >= 2]
        all_results = []

        # 1. Busca por termos combinados (AND) - Mais preciso
        if len(words) >= 2:
            where = " AND ".join(["conteudo ILIKE %s" for _ in words])
            params = [f"%{w}%" for w in words]
            cursor.execute(f"SELECT conteudo FROM documentos WHERE {where} LIMIT 5", params)
            for r in cursor.fetchall(): all_results.append(r['conteudo'])

        # 2. Busca por palavras individuais (OR) - Se a primeira falhar
        if not all_results:
            for w in words:
                if w not in ["quem", "da", "do", "rota"]:
                    cursor.execute("SELECT conteudo FROM documentos WHERE conteudo ILIKE %s LIMIT 3", (f"%{w}%",))
                    for r in cursor.fetchall(): all_results.append(r['conteudo'])
        
        conn.close()
        return "\n\n".join(list(dict.fromkeys(all_results))[:10])
    except Exception as e:
        return f"ERRO NA BUSCA: {str(e)}"

@app.route("/api/ask", methods=["POST", "OPTIONS"])
def ask():
    if request.method == "OPTIONS": return jsonify({"status": "ok"}), 200
    data = request.json
    question = data.get("question")
    context = get_context(question)

    def generate():
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model = genai.GenerativeModel("gemini-flash-latest")
        # Prompt mais agressivo para forçar o uso do contexto
        prompt = f"VOCÊ É O ESPECIALISTA JB. USE O CONTEXTO ABAIXO PARA RESPONDER A PERGUNTA.\nCONTEXTO:\n{context}\n\nPERGUNTA: {question}\n\nResponda apenas o dado solicitado."
        try:
            response = model.generate_content(prompt, stream=True)
            for chunk in response:
                if chunk.text: yield f"data: {json.dumps({'text': chunk.text})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e: yield f"data: {json.dumps({'text': str(e)})}\n\n"
    return Response(generate(), mimetype="text/event-stream")

# Mantendo as outras rotas (login, etc) simplificadas para o gunicorn
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

@app.route("/api/conversations", methods=["GET", "POST", "OPTIONS"])
def conversations():
    if request.method == "OPTIONS": return jsonify({"status": "ok"}), 200
    user_id = request.args.get("user_id") or (request.json.get("user_id") if request.is_json else None)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    if request.method == "POST":
        cur.execute("INSERT INTO conversas (user_id, titulo) VALUES (%s, %s) RETURNING id", (user_id, request.json.get("titulo", "Conversa")))
        chat_id = cur.fetchone()["id"]
        conn.commit()
        conn.close()
        return jsonify({"id": chat_id})
    cur.execute("SELECT id, titulo FROM conversas WHERE user_id = %s ORDER BY id DESC", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return jsonify(rows)

@app.route("/api/messages/<int:id>")
def messages(id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT role, content FROM mensagens WHERE conversa_id = %s ORDER BY id ASC", (id,))
    rows = cur.fetchall()
    conn.close()
    return jsonify(rows)

if __name__ == "__main__":
    app.run()
