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

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_db_connection():
    db_url = os.getenv("DATABASE_URL")
    if not db_url: return None
    if "supabase.com" in db_url and "sslmode" not in db_url:
        db_url += "&sslmode=require" if "?" in db_url else "?sslmode=require"
    return psycopg2.connect(db_url)

def get_context(query, history=None):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        clean_query = query.lower().strip()
        all_results = []
        
        # 1. BUSCA NO TREINAMENTO (EXCEL)
        cursor.execute("SELECT resposta_correta FROM treinamento_ia WHERE %s ILIKE '%%' || pergunta || '%%' OR pergunta ILIKE '%%' || %s || '%%' LIMIT 1", (clean_query, clean_query))
        train = cursor.fetchone()
        if train:
            all_results.append(f"CONHECIMENTO: {train['resposta_correta']}")

        # 2. BUSCA NA D23 (MELHORADA PARA CÓDIGOS CURTOS COMO 'FOR' OU '101')
        # Pega todas as palavras com 3 ou mais letras, ou que tenham números
        words = [w for w in clean_query.split() if len(w) >= 3 or any(char.isdigit() for char in w)]
        
        for w in words:
            # Busca agressiva: Procura a palavra cercada de espaços ou no início/fim para ser exato
            cursor.execute("SELECT conteudo FROM documentos WHERE conteudo ILIKE %s LIMIT 8", (f"%{w}%",))
            for r in cursor.fetchall():
                all_results.append(r['conteudo'])
        
        conn.close()
        return "\n\n".join(list(dict.fromkeys(all_results))[:15])
    except:
        return ""

@app.route("/api/login", methods=["POST", "OPTIONS"])
def login():
    if request.method == "OPTIONS": return jsonify({"status": "ok"}), 200
    data = request.json
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, username, role FROM usuarios WHERE username = %s AND password = %s", 
                       (data.get("username"), hash_password(data.get("password"))))
        user = cursor.fetchone()
        conn.close()
        if user: return jsonify({"status": "success", "user": user})
        return jsonify({"status": "error"}), 401
    except Exception as e: return jsonify({"error": str(e)}), 500

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
        Você é o Especialista JB. Responda curto e grosso.
        Use os dados abaixo para responder. Se não tiver o dado exato, diga que não consta.
        
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

@app.route("/api/conversations", methods=["GET", "POST", "OPTIONS"])
def conversations():
    if request.method == "OPTIONS": return jsonify({"status": "ok"}), 200
    user_id = request.args.get("user_id") or (request.json.get("user_id") if request.is_json else None)
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    if request.method == "POST":
        cursor.execute("INSERT INTO conversas (user_id, titulo) VALUES (%s, %s) RETURNING id", (user_id, request.json.get("titulo", "Conversa")))
        chat_id = cursor.fetchone()["id"]
        conn.commit()
        conn.close()
        return jsonify({"id": chat_id})
    cursor.execute("SELECT id, titulo FROM conversas WHERE user_id = %s ORDER BY id DESC", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return jsonify(rows)

@app.route("/api/messages/<int:id>")
def messages(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT role, content FROM mensagens WHERE conversa_id = %s ORDER BY id ASC", (id,))
    rows = cursor.fetchall()
    conn.close()
    return jsonify(rows)

if __name__ == "__main__":
    app.run()
