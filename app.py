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

def get_context(query):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        clean_query = query.lower().strip()
        
        # Palavras importantes (ignora "quem", "e", "o", "da", etc)
        ignore = ["quem", "e", "o", "a", "da", "do", "de", "qual", "motorista", "rota", "subrota"]
        words = [w for w in clean_query.split() if w not in ignore and (len(w) >= 3 or any(c.isdigit() for c in w))]
        
        all_results = []
        
        # 1. BUSCA NO TREINAMENTO
        cursor.execute("SELECT resposta_correta FROM treinamento_ia WHERE %s ILIKE '%%' || pergunta || '%%' LIMIT 1", (clean_query,))
        train = cursor.fetchone()
        if train: all_results.append(f"TREINAMENTO: {train['resposta_correta']}")

        # 2. BUSCA DE PRECISÃO (Lógica AND - Todas as palavras na mesma linha)
        if words:
            # Constrói a query: WHERE conteudo ILIKE %w1% AND conteudo ILIKE %w2% ...
            where_clause = " AND ".join(["conteudo ILIKE %s" for _ in words])
            params = [f"%{w}%" for w in words]
            cursor.execute(f"SELECT conteudo FROM documentos WHERE {where_clause} LIMIT 10", params)
            for r in cursor.fetchall():
                all_results.append(r['conteudo'])

        # 3. BUSCA DE BACKUP (Se a de precisão falhar, tenta palavras isoladas)
        if not all_results and words:
            for w in words[:2]:
                cursor.execute("SELECT conteudo FROM documentos WHERE conteudo ILIKE %s LIMIT 5", (f"%{w}%",))
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
        prompt = f"Use o CONTEXTO abaixo para responder a PERGUNTA de forma curta.\nCONTEXTO:\n{context}\n\nPERGUNTA: {question}"
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
